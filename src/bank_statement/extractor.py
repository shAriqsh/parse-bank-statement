import asyncio
from decimal import Decimal
import io
import os
from pathlib import Path
import re
from typing import Any
from google import genai
from google.genai import types
import pdfplumber
from pydantic import BaseModel, Field
from bank_statement.config import load_gemini_api_key
from bank_statement.models import Transaction

__all__ = [
    "EXTRACTION_PROMPT",
    "ExtractedPage",
    "ExtractedTransaction",
    "extract_page_transactions",
    "extract_statement_transactions",
    "is_rate_limit_error",
]


def _clean_monetary_amount(value: str | None, default: str = "0.00") -> Decimal:
    """Clean and parse a monetary amount string into Decimal."""
    if value is None:
        return Decimal(default)
    cleaned = value.strip().replace(",", "")
    cleaned = re.sub(r"^(?:INR|Rs\.?|\$|£|€)\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*(?:INR|Rs\.?|\$|£|€)$", "", cleaned, flags=re.IGNORECASE).strip()

    is_dr = bool(re.search(r"\(?\s*Dr\s*\)?", cleaned, flags=re.IGNORECASE))
    cleaned = re.sub(r"\(?\s*(?:Cr|Dr)\s*\)?", "", cleaned, flags=re.IGNORECASE).strip()

    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1].strip()

    cleaned = re.sub(r"^-\s*", "-", cleaned).strip()

    if not cleaned or cleaned in ("-", "--", "nil", "null"):
        return Decimal(default)

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return Decimal(default)

    result = Decimal(match.group(0))
    if is_dr and result > 0:
        result = -result
    return result


class ExtractedTransaction(BaseModel):
    """Raw transaction extracted from multimodal vision output."""

    date: str
    narration: str
    chq_ref_no: str | None = None
    withdrawal: str = "0.00"
    deposit: str = "0.00"
    balance: str

    def to_domain_transaction(self) -> Transaction:
        return Transaction(
            date=self.date.strip(),
            narration=self.narration.strip(),
            chq_ref_no=self.chq_ref_no.strip() if self.chq_ref_no and self.chq_ref_no.strip() else None,
            withdrawal=_clean_monetary_amount(self.withdrawal, default="0.00"),
            deposit=_clean_monetary_amount(self.deposit, default="0.00"),
            running_balance=_clean_monetary_amount(self.balance, default="0.00"),
        )


class ExtractedPage(BaseModel):
    """Collection of transactions extracted from a single statement page."""

    transactions: list[ExtractedTransaction] = Field(default_factory=list)


EXTRACTION_PROMPT = """You are an expert financial auditor extracting tabular transactions from this rasterized bank statement page.

CRITICAL EXTRACTION DIRECTIVES:
1. Extract every legitimate transaction row appearing in the table on this page.
2. NARRATION MERGING: If a transaction narration spans across multiple wrapped lines or rows (such as remarks, account numbers, or merchant details), MERGE them cleanly into a single continuous string.
3. EXCLUSIONS: Do NOT extract recurring table column headers, page headers, bank names, branch addresses, account holder details, footer lines, page numbers, or carry-forward / brought-forward lines (such as "Balance B/F", "Brought Forward", "Carried Forward", "Balance C/F").
4. AMOUNTS & ZERO VALUES: For each transaction row, extract date, narration, chq_ref_no (if present, else null), withdrawal amount, deposit amount, and running balance. If withdrawal or deposit is empty, absent, or dash ('-'), represent it strictly as "0.00".
5. OUTPUT FORMAT: Respond strictly conforming to the requested schema.
"""


def extract_page_transactions(
    image_bytes: bytes,
    client: genai.Client | None = None,
) -> list[Transaction]:
    """Extract structured transactions from a bank statement page image.

    Args:
        image_bytes: PNG or JPEG image byte array of the statement page.
        client: Optional preconfigured genai.Client instance. If not provided,
            a new client is initialized using the GEMINI_API_KEY environment variable.

    Returns:
        List of domain Transaction models for all transactions detected on the page.
    """
    if client is None:
        api_key = load_gemini_api_key()
        client = genai.Client(api_key=api_key)

    contents: Any = [
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        types.Part.from_text(text=EXTRACTION_PROMPT),
    ]

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedPage,
        ),
    )

    extracted_page: ExtractedPage | None = None
    if getattr(response, "parsed", None) is not None and isinstance(
        response.parsed, ExtractedPage
    ):
        extracted_page = response.parsed
    else:
        text_content = getattr(response, "text", None)
        if isinstance(text_content, str) and text_content.strip():
            extracted_page = ExtractedPage.model_validate_json(text_content)
        else:
            extracted_page = ExtractedPage(transactions=[])

    return [t.to_domain_transaction() for t in extracted_page.transactions]


def _rasterize_pdf_pages(
    pdf_path: str | Path,
    resolution: int = 150,
    max_pages: int | None = None,
) -> list[bytes]:
    """Inspect and rasterize all pages of a PDF document into in-memory PNG image bytes in a single pass."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        buffers: list[bytes] = []
        pages = pdf.pages[:max_pages] if max_pages is not None else pdf.pages
        for page in pages:
            page_image = page.to_image(resolution=resolution)
            buf = io.BytesIO()
            page_image.original.save(buf, format="PNG")
            buffers.append(buf.getvalue())
        return buffers


def is_rate_limit_error(exc: Exception) -> bool:
    """Determine whether an exception represents an HTTP 429 rate limit or transient 503 unavailable error."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, "429", 503, "503"):
        return True
    msg = str(exc).upper()
    return (
        "429" in msg
        or "503" in msg
        or "RESOURCE_EXHAUSTED" in msg
        or "RATE_LIMIT" in msg
        or "QUOTA EXCEEDED" in msg
        or "TOO MANY REQUESTS" in msg
        or "UNAVAILABLE" in msg
        or "HIGH DEMAND" in msg
    )


async def extract_statement_transactions(
    pdf_path: str | Path,
    client: Any = None,
    max_concurrency: int = 5,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    resolution: int = 150,
    max_pages: int | None = None,
) -> list[Transaction]:
    """Extract transactions from all pages of a PDF statement with concurrent execution and retry handling.

    Args:
        pdf_path: Path to the bank statement PDF file.
        client: Optional Gemini client instance.
        max_concurrency: Maximum number of concurrent page extractions.
        max_retries: Maximum retries on transient rate-limit errors.
        retry_base_delay: Base delay in seconds for exponential backoff.
        resolution: DPI resolution for PDF page rasterization.
        max_pages: Optional maximum number of pages to process.

    Returns:
        Chronologically sorted list of domain Transaction instances across all pages.
    """
    loop = asyncio.get_running_loop()
    page_buffers = await loop.run_in_executor(
        None, _rasterize_pdf_pages, pdf_path, resolution, max_pages
    )

    semaphore = asyncio.Semaphore(max_concurrency)

    async def worker(page_idx: int, img_bytes: bytes) -> tuple[int, list[Transaction]]:
        for attempt in range(max_retries + 1):
            try:
                async with semaphore:
                    txs = await loop.run_in_executor(
                        None, extract_page_transactions, img_bytes, client
                    )
                    return page_idx, txs
            except Exception as exc:
                if attempt < max_retries and is_rate_limit_error(exc):
                    delay = retry_base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                raise
        raise RuntimeError(f"Failed to extract page {page_idx} after {max_retries} retries")

    tasks = [worker(idx, buf) for idx, buf in enumerate(page_buffers)]
    raw_results = await asyncio.gather(*tasks)

    sorted_results = sorted(raw_results, key=lambda item: item[0])
    all_transactions: list[Transaction] = []
    for _, page_txs in sorted_results:
        all_transactions.extend(page_txs)

    return all_transactions


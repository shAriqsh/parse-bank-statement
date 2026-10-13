from decimal import Decimal
import threading
import time
from typing import Any
from unittest.mock import MagicMock
import pytest
from google.genai import types
from bank_statement.extractor import (
    EXTRACTION_PROMPT,
    ExtractedPage,
    ExtractedTransaction,
    extract_page_transactions,
    extract_statement_transactions,
)
from bank_statement.models import Transaction


def test_extract_page_transactions_with_mock_client_parsed_response() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed = ExtractedPage(
        transactions=[
            ExtractedTransaction(
                date="01-01-2024",
                narration="OPENING DEPOSIT BY TRANSFER",
                chq_ref_no=None,
                withdrawal="0.00",
                deposit="10,000.00",
                balance="10,000.00",
            ),
            ExtractedTransaction(
                date="02-01-2024",
                narration="ELECTRICITY BILL PAYMENT AUTODEBIT",
                chq_ref_no="TXN-4491",
                withdrawal="1,200.50",
                deposit="0.00",
                balance="8,799.50",
            ),
        ]
    )
    mock_client.models.generate_content.return_value = mock_response

    fake_png_bytes = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    transactions = extract_page_transactions(fake_png_bytes, client=mock_client)

    assert len(transactions) == 2
    assert isinstance(transactions[0], Transaction)
    assert transactions[0].deposit == Decimal("10000.00")
    assert transactions[0].running_balance == Decimal("10000.00")
    assert transactions[1].withdrawal == Decimal("1200.50")
    assert transactions[1].running_balance == Decimal("8799.50")
    assert transactions[1].chq_ref_no == "TXN-4491"

    # Verify call parameters
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-3.5-flash-lite"
    assert "contents" in call_kwargs
    assert "config" in call_kwargs


def test_extract_page_transactions_with_json_text_fallback() -> None:
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = '{"transactions": [{"date": "05-01-2024", "narration": "GROCERY STORE", "chq_ref_no": null, "withdrawal": "450.00", "deposit": "0.00", "balance": "8349.50"}]}'
    mock_client.models.generate_content.return_value = mock_response

    fake_png_bytes = b"\x89PNG\r\n\x1a\nfakeimagebytes"
    transactions = extract_page_transactions(fake_png_bytes, client=mock_client)

    assert len(transactions) == 1
    assert transactions[0].narration == "GROCERY STORE"
    assert transactions[0].withdrawal == Decimal("450.00")
    assert transactions[0].running_balance == Decimal("8349.50")


def test_prompt_contains_critical_directives() -> None:
    assert "NARRATION MERGING" in EXTRACTION_PROMPT or "merge" in EXTRACTION_PROMPT.lower()
    assert "Balance B/F" in EXTRACTION_PROMPT or "carry-forward" in EXTRACTION_PROMPT.lower()
    assert "0.00" in EXTRACTION_PROMPT


class SimulatedVisionClient:
    """Simulated Gemini vision client for testing extraction adapter resilience and ordering."""

    def __init__(
        self,
        responses: dict[bytes, ExtractedPage] | None = None,
        delays: dict[bytes, float] | None = None,
        errors: dict[bytes, list[Exception]] | None = None,
        track_concurrency: bool = False,
    ) -> None:
        self.responses = responses or {}
        self.delays = delays or {}
        self.errors = errors or {}
        self.track_concurrency = track_concurrency
        self.calls: list[bytes] = []
        self.active_workers: int = 0
        self.max_active_observed: int = 0
        self._lock = threading.Lock()
        self.models = self

    def generate_content(
        self,
        model: str,
        contents: list[Any],
        config: Any = None,
    ) -> Any:
        image_part = contents[0]
        data: bytes = getattr(getattr(image_part, "inline_data", None), "data", b"")
        self.calls.append(data)

        if self.track_concurrency:
            with self._lock:
                self.active_workers += 1
                if self.active_workers > self.max_active_observed:
                    self.max_active_observed = self.active_workers

        try:
            if data in self.errors and self.errors[data]:
                exc = self.errors[data].pop(0)
                raise exc

            if data in self.delays:
                time.sleep(self.delays[data])

            mock_resp = MagicMock()
            mock_resp.parsed = self.responses.get(data, ExtractedPage(transactions=[]))
            return mock_resp
        finally:
            if self.track_concurrency:
                with self._lock:
                    self.active_workers -= 1


@pytest.mark.anyio
async def test_extract_statement_transactions_preserves_page_order_despite_async_completion_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p0, p1, p2 = b"page_0", b"page_1", b"page_2"
    def mock_rasterize_3_pages(
        _path: object,
        _resolution: int = 150,
        _max_pages: int | None = None,
    ) -> list[bytes]:
        return [p0, p1, p2]

    monkeypatch.setattr(
        "bank_statement.extractor._rasterize_pdf_pages",
        mock_rasterize_3_pages,
    )

    client = SimulatedVisionClient(
        responses={
            p0: ExtractedPage(
                transactions=[
                    ExtractedTransaction(
                        date="01-01-2024",
                        narration="PAGE 0 TRANSACTION",
                        withdrawal="0.00",
                        deposit="1000.00",
                        balance="1000.00",
                    )
                ]
            ),
            p1: ExtractedPage(
                transactions=[
                    ExtractedTransaction(
                        date="02-01-2024",
                        narration="PAGE 1 TRANSACTION",
                        withdrawal="200.00",
                        deposit="0.00",
                        balance="800.00",
                    )
                ]
            ),
            p2: ExtractedPage(
                transactions=[
                    ExtractedTransaction(
                        date="03-01-2024",
                        narration="PAGE 2 TRANSACTION",
                        withdrawal="0.00",
                        deposit="500.00",
                        balance="1300.00",
                    )
                ]
            ),
        },
        delays={
            p0: 0.05,
            p1: 0.02,
            p2: 0.001,
        },
    )

    txs = await extract_statement_transactions("dummy.pdf", client=client)

    assert len(txs) == 3
    assert [tx.narration for tx in txs] == [
        "PAGE 0 TRANSACTION",
        "PAGE 1 TRANSACTION",
        "PAGE 2 TRANSACTION",
    ]
    assert txs[0].running_balance == Decimal("1000.00")
    assert txs[1].running_balance == Decimal("800.00")
    assert txs[2].running_balance == Decimal("1300.00")


@pytest.mark.anyio
async def test_extract_statement_transactions_concurrency_bounded_by_semaphore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [f"page_{i}".encode("utf-8") for i in range(10)]
    def mock_rasterize_10_pages(
        _path: object,
        _resolution: int = 150,
        _max_pages: int | None = None,
    ) -> list[bytes]:
        return pages

    monkeypatch.setattr(
        "bank_statement.extractor._rasterize_pdf_pages",
        mock_rasterize_10_pages,
    )

    max_concurrency = 3
    client = SimulatedVisionClient(
        responses={
            p: ExtractedPage(
                transactions=[
                    ExtractedTransaction(
                        date="01-01-2024",
                        narration=f"PAGE {i}",
                        withdrawal="0.00",
                        deposit="100.00",
                        balance="100.00",
                    )
                ]
            )
            for i, p in enumerate(pages)
        },
        delays={p: 0.03 for p in pages},
        track_concurrency=True,
    )

    txs = await extract_statement_transactions(
        "dummy.pdf",
        client=client,
        max_concurrency=max_concurrency,
    )

    assert len(txs) == 10
    assert client.max_active_observed <= max_concurrency
    assert client.max_active_observed > 1


class SimulatedRateLimitError(Exception):
    def __init__(self, message: str = "429 RESOURCE_EXHAUSTED: Quota exceeded", code: int = 429) -> None:
        super().__init__(message)
        self.code = code


@pytest.mark.anyio
async def test_extract_statement_transactions_retries_transient_rate_limit_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p0 = b"page_flaky"
    def mock_rasterize_flaky(
        _path: object,
        _resolution: int = 150,
        _max_pages: int | None = None,
    ) -> list[bytes]:
        return [p0]

    monkeypatch.setattr(
        "bank_statement.extractor._rasterize_pdf_pages",
        mock_rasterize_flaky,
    )

    client = SimulatedVisionClient(
        responses={
            p0: ExtractedPage(
                transactions=[
                    ExtractedTransaction(
                        date="01-01-2024",
                        narration="RECOVERED TRANSACTION",
                        withdrawal="0.00",
                        deposit="500.00",
                        balance="500.00",
                    )
                ]
            )
        },
        errors={
            p0: [
                SimulatedRateLimitError("429 RESOURCE_EXHAUSTED", code=429),
                SimulatedRateLimitError("503 Service Unavailable", code=503),
            ]
        },
    )

    txs = await extract_statement_transactions(
        "dummy.pdf",
        client=client,
        max_retries=3,
        retry_base_delay=0.01,
    )

    assert len(txs) == 1
    assert txs[0].narration == "RECOVERED TRANSACTION"
    assert len(client.calls) == 3


@pytest.mark.anyio
async def test_extract_statement_transactions_non_transient_client_error_raises_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p0 = b"page_bad_auth"
    def mock_rasterize_bad_auth(
        _path: object,
        _resolution: int = 150,
        _max_pages: int | None = None,
    ) -> list[bytes]:
        return [p0]

    monkeypatch.setattr(
        "bank_statement.extractor._rasterize_pdf_pages",
        mock_rasterize_bad_auth,
    )

    client = SimulatedVisionClient(
        errors={
            p0: [
                ValueError("Invalid API key or authentication credentials"),
            ]
        },
    )

    with pytest.raises(ValueError, match="Invalid API key or authentication credentials"):
        await extract_statement_transactions(
            "dummy.pdf",
            client=client,
            max_retries=3,
            retry_base_delay=0.01,
        )

    assert len(client.calls) == 1


@pytest.mark.anyio
async def test_extract_statement_transactions_unreadable_file_raises_immediately() -> None:
    with pytest.raises(FileNotFoundError):
        await extract_statement_transactions("non_existent_file_path_12345.pdf")


@pytest.mark.anyio
async def test_extract_statement_transactions_end_to_end_rasterization_with_real_pdf() -> None:
    # Use real account.pdf fixture with max_pages=2 to test end-to-end PDF opening & rasterization
    called_pages: list[bytes] = []

    def make_response(data: bytes) -> ExtractedPage:
        called_pages.append(data)
        idx = len(called_pages)
        return ExtractedPage(
            transactions=[
                ExtractedTransaction(
                    date=f"0{idx}-01-2024",
                    narration=f"REAL PDF PAGE {idx} TRANSACTION",
                    withdrawal="0.00",
                    deposit=f"{idx * 100}.00",
                    balance=f"{idx * 100}.00",
                )
            ]
        )

    def mock_generate_content(
        *args: object,
        contents: list[Any],
        **kwargs: object,
    ) -> MagicMock:
        return MagicMock(
            parsed=make_response(getattr(getattr(contents[0], "inline_data", None), "data", b""))
        )

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    txs = await extract_statement_transactions(
        "account.pdf",
        client=mock_client,
        resolution=36,
        max_pages=2,
    )

    assert len(txs) == 2
    assert len(called_pages) == 2
    # Verify both rasterized pages are valid PNGs
    for img_buf in called_pages:
        assert img_buf.startswith(b"\x89PNG\r\n\x1a\n")
    assert txs[0].narration == "REAL PDF PAGE 1 TRANSACTION"
    assert txs[1].narration == "REAL PDF PAGE 2 TRANSACTION"
    assert txs[0].deposit == Decimal("100.00")
    assert txs[1].deposit == Decimal("200.00")






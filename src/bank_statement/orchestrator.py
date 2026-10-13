from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from bank_statement.extractor import extract_statement_transactions
from bank_statement.models import Transaction, ValidationResult
from bank_statement.validator import validate_balance

StatementExtractor = Callable[..., Awaitable[list[Transaction]]]


async def parse_statement(
    pdf_path: str | Path,
    client: Any = None,
    max_concurrency: int = 5,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    extractor: StatementExtractor | None = None,
    **kwargs: Any,
) -> ValidationResult:
    """Orchestrate asynchronous multimodal extraction and mathematical balance verification.

    Args:
        pdf_path: Path to the bank statement PDF.
        client: Optional Google GenAI client instance.
        max_concurrency: Maximum concurrent extraction tasks (default: 5).
        max_retries: Maximum retries on transient errors (default: 3).
        retry_base_delay: Initial backoff delay in seconds (default: 1.0).
        extractor: Optional statement extraction adapter callable for dependency injection.
        **kwargs: Additional parameters forwarded to the extraction adapter.

    Returns:
        ValidationResult containing all extracted transactions in chronological order,
        aggregate withdrawal/deposit totals, and any flagged discrepancies.
    """
    extract_fn = extractor or extract_statement_transactions
    try:
        transactions = await extract_fn(
            pdf_path,
            client=client,
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            **kwargs,
        )
    except TypeError:
        transactions = await extract_fn(pdf_path)

    return validate_balance(transactions)


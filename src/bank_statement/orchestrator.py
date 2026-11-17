from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any
from bank_statement.extractor import extract_statement_transactions
from bank_statement.models import (
    BatchValidationResult,
    StatementResult,
    Transaction,
    ValidationResult,
)
from bank_statement.validator import validate_balance

StatementExtractor = Callable[..., Awaitable[list[Transaction]]]


async def parse_statement(
    pdf_path: str | Path,
    client: Any = None,
    max_concurrency: int = 5,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    extractor: StatementExtractor | None = None,
    progress_callback: Callable[[str, float | None], None] | None = None,
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
        progress_callback: Optional progress callback hook.
        **kwargs: Additional parameters forwarded to the extraction adapter.

    Returns:
        ValidationResult containing all extracted transactions in chronological order,
        aggregate withdrawal/deposit totals, and any flagged discrepancies.
    """
    extract_fn = extractor or extract_statement_transactions
    call_kwargs: dict[str, Any] = {
        "client": client,
        "max_concurrency": max_concurrency,
        "max_retries": max_retries,
        "retry_base_delay": retry_base_delay,
        **kwargs,
    }
    if progress_callback is not None:
        call_kwargs["progress_callback"] = progress_callback

    try:
        transactions = await extract_fn(pdf_path, **call_kwargs)
    except TypeError:
        transactions = await extract_fn(pdf_path)

    return validate_balance(transactions)



async def parse_batch_statements(
    pdf_paths: Iterable[str | Path],
    client: Any = None,
    max_concurrency: int = 5,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    extractor: StatementExtractor | None = None,
    **kwargs: Any,
) -> BatchValidationResult:
    """Orchestrate sequential extraction and isolated balance verification for a batch of statement PDFs.

    Args:
        pdf_paths: Iterable of paths to statement PDFs.
        client: Optional Google GenAI client instance.
        max_concurrency: Maximum concurrent extraction tasks per statement (default: 5).
        max_retries: Maximum retries on transient errors (default: 3).
        retry_base_delay: Initial backoff delay in seconds (default: 1.0).
        extractor: Optional statement extraction adapter callable for dependency injection.
        **kwargs: Additional parameters forwarded to the extraction adapter.

    Returns:
        BatchValidationResult containing aggregated totals, discrepancy counts, overall validity,
        and per-statement validation or failure results.
    """
    statement_results: list[StatementResult] = []

    for path_item in pdf_paths:
        current_path = Path(path_item)
        try:
            val_result = await parse_statement(
                pdf_path=current_path,
                client=client,
                max_concurrency=max_concurrency,
                max_retries=max_retries,
                retry_base_delay=retry_base_delay,
                extractor=extractor,
                **kwargs,
            )
            statement_results.append(
                StatementResult(
                    pdf_path=current_path,
                    status="success",
                    result=val_result,
                )
            )
        except Exception as exc:
            statement_results.append(
                StatementResult(
                    pdf_path=current_path,
                    status="failed",
                    error=str(exc),
                )
            )

    total_statements = len(statement_results)
    successful_count = sum(1 for s in statement_results if s.status == "success")
    failed_count = sum(1 for s in statement_results if s.status == "failed")
    cumulative_withdrawals = sum(
        (s.result.total_withdrawals for s in statement_results if s.result is not None),
        Decimal("0.00"),
    )
    cumulative_deposits = sum(
        (s.result.total_deposits for s in statement_results if s.result is not None),
        Decimal("0.00"),
    )
    total_discrepancies = sum(
        (len(s.result.discrepancies) for s in statement_results if s.result is not None),
        0,
    )
    is_valid = failed_count == 0 and total_discrepancies == 0

    return BatchValidationResult(
        total_statements=total_statements,
        successful_count=successful_count,
        failed_count=failed_count,
        cumulative_withdrawals=cumulative_withdrawals,
        cumulative_deposits=cumulative_deposits,
        total_discrepancies=total_discrepancies,
        is_valid=is_valid,
        statements=statement_results,
    )


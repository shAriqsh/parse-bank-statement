from decimal import Decimal
from pathlib import Path
import pytest
from pydantic import ValidationError

from bank_statement.models import (
    BatchValidationResult,
    StatementResult,
    Transaction,
    ValidationResult,
)


def test_statement_result_success_instantiation() -> None:
    validation = ValidationResult(
        transactions=[],
        total_withdrawals=Decimal("100.00"),
        total_deposits=Decimal("200.00"),
        discrepancies=[],
        is_valid=True,
    )
    stmt = StatementResult(
        pdf_path=Path("statement_jan.pdf"),
        status="success",
        result=validation,
    )

    assert stmt.pdf_path == Path("statement_jan.pdf")
    assert stmt.status == "success"
    assert stmt.result == validation
    assert stmt.error is None


def test_statement_result_failed_instantiation() -> None:
    stmt = StatementResult(
        pdf_path=Path("corrupt.pdf"),
        status="failed",
        error="PDF file is corrupted or empty",
    )

    assert stmt.pdf_path == Path("corrupt.pdf")
    assert stmt.status == "failed"
    assert stmt.result is None
    assert stmt.error == "PDF file is corrupted or empty"


def test_statement_result_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        StatementResult(
            pdf_path=Path("statement.pdf"),
            status="pending",  # type: ignore[arg-type]
        )


def test_batch_validation_result_instantiation() -> None:
    stmt1 = StatementResult(
        pdf_path=Path("s1.pdf"),
        status="success",
        result=ValidationResult(
            transactions=[],
            total_withdrawals=Decimal("50.00"),
            total_deposits=Decimal("150.00"),
            discrepancies=[],
            is_valid=True,
        ),
    )
    stmt2 = StatementResult(
        pdf_path=Path("s2.pdf"),
        status="failed",
        error="File unreadable",
    )
    batch = BatchValidationResult(
        total_statements=2,
        successful_count=1,
        failed_count=1,
        cumulative_withdrawals=Decimal("50.00"),
        cumulative_deposits=Decimal("150.00"),
        total_discrepancies=0,
        is_valid=False,
        statements=[stmt1, stmt2],
    )

    assert batch.total_statements == 2
    assert batch.successful_count == 1
    assert batch.failed_count == 1
    assert batch.cumulative_withdrawals == Decimal("50.00")
    assert batch.cumulative_deposits == Decimal("150.00")
    assert batch.total_discrepancies == 0
    assert batch.is_valid is False
    assert len(batch.statements) == 2

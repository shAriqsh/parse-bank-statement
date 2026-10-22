from decimal import Decimal
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

__all__ = [
    "BatchValidationResult",
    "Discrepancy",
    "StatementResult",
    "Transaction",
    "ValidationResult",
]


class Discrepancy(BaseModel):
    """Details of a mathematical balance discrepancy on a transaction."""

    expected_balance: Decimal
    stated_balance: Decimal
    delta: Decimal


class Transaction(BaseModel):
    """An individual debit or credit entry on a bank statement."""

    date: str
    narration: str
    chq_ref_no: str | None = None
    withdrawal: Decimal = Field(default_factory=lambda: Decimal("0.00"))
    deposit: Decimal = Field(default_factory=lambda: Decimal("0.00"))
    running_balance: Decimal
    discrepancy: Discrepancy | None = None


class ValidationResult(BaseModel):
    """Results of mathematical balance verification across transactions."""

    transactions: list[Transaction]
    total_withdrawals: Decimal
    total_deposits: Decimal
    discrepancies: list[Transaction]
    is_valid: bool


class StatementResult(BaseModel):
    """Result of processing an individual statement PDF within a batch."""

    pdf_path: Path
    status: Literal["success", "failed"]
    result: ValidationResult | None = None
    error: str | None = None


class BatchValidationResult(BaseModel):
    """Aggregated validation results and financial metrics across a batch of statements."""

    total_statements: int
    successful_count: int
    failed_count: int
    cumulative_withdrawals: Decimal
    cumulative_deposits: Decimal
    total_discrepancies: int
    is_valid: bool
    statements: list[StatementResult]

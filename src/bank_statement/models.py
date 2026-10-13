from decimal import Decimal
from pydantic import BaseModel, Field

__all__ = ["Discrepancy", "Transaction", "ValidationResult"]


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

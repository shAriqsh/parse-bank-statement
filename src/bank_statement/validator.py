from decimal import Decimal
from bank_statement.models import Discrepancy, Transaction, ValidationResult


def validate_balance(transactions: list[Transaction]) -> ValidationResult:
    """Validate mathematical consistency across a sequence of transactions.

    1. Establishes the initial transaction as the baseline balance.
    2. Sequentially verifies: expected = previous_balance - withdrawal + deposit == current_balance.
    3. On discrepancy: records expected balance, stated balance, and delta (stated - expected),
       marks discrepancy on the transaction, and re-anchors expected balance to the stated running balance.
    4. Computes total withdrawals and total deposits across all transactions.
    """
    if not transactions:
        return ValidationResult(
            transactions=[],
            total_withdrawals=Decimal("0.00"),
            total_deposits=Decimal("0.00"),
            discrepancies=[],
            is_valid=True,
        )

    validated_transactions: list[Transaction] = []
    discrepancies: list[Transaction] = []

    # Baseline balance established from first transaction
    first_tx = transactions[0].model_copy()
    first_tx.discrepancy = None
    validated_transactions.append(first_tx)
    previous_balance = first_tx.running_balance

    for tx in transactions[1:]:
        tx_copy = tx.model_copy()
        expected_balance = previous_balance - tx_copy.withdrawal + tx_copy.deposit

        if expected_balance != tx_copy.running_balance:
            delta = tx_copy.running_balance - expected_balance
            tx_copy.discrepancy = Discrepancy(
                expected_balance=expected_balance,
                stated_balance=tx_copy.running_balance,
                delta=delta,
            )
            discrepancies.append(tx_copy)
            # Re-anchor to the stated running balance
            previous_balance = tx_copy.running_balance
        else:
            tx_copy.discrepancy = None
            previous_balance = tx_copy.running_balance

        validated_transactions.append(tx_copy)

    total_withdrawals = sum((tx.withdrawal for tx in transactions), Decimal("0.00"))
    total_deposits = sum((tx.deposit for tx in transactions), Decimal("0.00"))

    return ValidationResult(
        transactions=validated_transactions,
        total_withdrawals=total_withdrawals,
        total_deposits=total_deposits,
        discrepancies=discrepancies,
        is_valid=len(discrepancies) == 0,
    )

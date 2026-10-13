from decimal import Decimal
from bank_statement.models import Transaction, ValidationResult
from bank_statement.validator import validate_balance


def test_baseline_balance_and_totals_for_single_transaction() -> None:
    tx = Transaction(
        date="01-01-2024",
        narration="OPENING BALANCE OR FIRST TRANSACTION",
        chq_ref_no=None,
        withdrawal=Decimal("0.00"),
        deposit=Decimal("1500.50"),
        running_balance=Decimal("1500.50"),
    )

    result = validate_balance([tx])

    assert isinstance(result, ValidationResult)
    assert result.is_valid is True
    assert result.total_withdrawals == Decimal("0.00")
    assert result.total_deposits == Decimal("1500.50")
    assert len(result.discrepancies) == 0
    assert len(result.transactions) == 1
    assert result.transactions[0].discrepancy is None


def test_balanced_transaction_chain() -> None:
    transactions = [
        Transaction(
            date="01-01-2024",
            narration="OPENING BALANCE",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("1000.00"),
            running_balance=Decimal("1000.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="ATM WITHDRAWAL",
            withdrawal=Decimal("200.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("800.00"),
        ),
        Transaction(
            date="03-01-2024",
            narration="SALARY CREDIT",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("550.25"),
            running_balance=Decimal("1350.25"),
        ),
        Transaction(
            date="04-01-2024",
            narration="UTILITY PAYMENT AND CASHBACK",
            withdrawal=Decimal("100.25"),
            deposit=Decimal("50.00"),
            running_balance=Decimal("1300.00"),
        ),
    ]

    result = validate_balance(transactions)

    assert result.is_valid is True
    assert len(result.discrepancies) == 0
    assert result.total_withdrawals == Decimal("300.25")
    assert result.total_deposits == Decimal("1600.25")
    assert all(tx.discrepancy is None for tx in result.transactions)


def test_single_debit_discrepancy_and_reanchoring() -> None:
    transactions = [
        Transaction(
            date="01-01-2024",
            narration="OPENING BALANCE",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("1000.00"),
            running_balance=Decimal("1000.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="WITHDRAWAL WITH ARITHMETIC ERROR",
            withdrawal=Decimal("200.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("750.00"),  # Expected: 800.00, Delta: -50.00
        ),
        Transaction(
            date="03-01-2024",
            narration="SUBSEQUENT NORMAL WITHDRAWAL",
            withdrawal=Decimal("50.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("700.00"),  # Matches re-anchored 750.00 - 50.00 = 700.00
        ),
    ]

    result = validate_balance(transactions)

    assert result.is_valid is False
    assert len(result.discrepancies) == 1
    flagged = result.transactions[1]
    assert flagged.discrepancy is not None
    assert flagged.discrepancy.expected_balance == Decimal("800.00")
    assert flagged.discrepancy.stated_balance == Decimal("750.00")
    assert flagged.discrepancy.delta == Decimal("-50.00")

    # Verify re-anchoring ensured Tx 3 did not falsely fail
    assert result.transactions[2].discrepancy is None


def test_single_credit_discrepancy_and_reanchoring() -> None:
    transactions = [
        Transaction(
            date="01-01-2024",
            narration="OPENING BALANCE",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("500.00"),
            running_balance=Decimal("500.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="DEPOSIT WITH ARITHMETIC ERROR",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("300.00"),
            running_balance=Decimal("850.00"),  # Expected: 800.00, Delta: +50.00
        ),
        Transaction(
            date="03-01-2024",
            narration="NORMAL WITHDRAWAL",
            withdrawal=Decimal("100.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("750.00"),  # Matches re-anchored 850.00 - 100.00 = 750.00
        ),
    ]

    result = validate_balance(transactions)

    assert result.is_valid is False
    assert len(result.discrepancies) == 1
    flagged = result.transactions[1]
    assert flagged.discrepancy is not None
    assert flagged.discrepancy.expected_balance == Decimal("800.00")
    assert flagged.discrepancy.stated_balance == Decimal("850.00")
    assert flagged.discrepancy.delta == Decimal("50.00")

    assert result.transactions[2].discrepancy is None


def test_multiple_non_adjacent_discrepancies() -> None:
    transactions = [
        Transaction(
            date="01-01-2024",
            narration="OPENING BASELINE",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("1000.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="FIRST ERROR (DEBIT)",
            withdrawal=Decimal("100.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("850.00"),  # Expected: 900.00, Delta: -50.00
        ),
        Transaction(
            date="03-01-2024",
            narration="NORMAL INTERMEDIATE WITHDRAWAL",
            withdrawal=Decimal("50.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("800.00"),  # Matches re-anchored 850 - 50 = 800
        ),
        Transaction(
            date="04-01-2024",
            narration="SECOND ERROR (CREDIT)",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("200.00"),
            running_balance=Decimal("1050.00"),  # Expected: 800 + 200 = 1000.00, Delta: +50.00
        ),
        Transaction(
            date="05-01-2024",
            narration="FINAL NORMAL WITHDRAWAL",
            withdrawal=Decimal("150.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("900.00"),  # Matches re-anchored 1050 - 150 = 900
        ),
    ]

    result = validate_balance(transactions)

    assert result.is_valid is False
    assert len(result.discrepancies) == 2
    assert result.discrepancies[0] == result.transactions[1]
    assert result.discrepancies[1] == result.transactions[3]

    assert result.transactions[0].discrepancy is None
    assert result.transactions[1].discrepancy is not None
    assert result.transactions[1].discrepancy.delta == Decimal("-50.00")
    assert result.transactions[2].discrepancy is None
    assert result.transactions[3].discrepancy is not None
    assert result.transactions[3].discrepancy.delta == Decimal("50.00")
    assert result.transactions[4].discrepancy is None

    assert result.total_withdrawals == Decimal("300.00")
    assert result.total_deposits == Decimal("200.00")


def test_exact_decimal_precision_and_floating_point_hazards() -> None:
    # Values that famously suffer from binary float precision drift
    transactions = [
        Transaction(
            date="01-01-2024",
            narration="OPENING BASELINE",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("100.07"),
        ),
        Transaction(
            date="02-01-2024",
            narration="TRANSACTION WITH FLOAT HAZARD",
            withdrawal=Decimal("70.03"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("30.04"),  # In float: 100.07 - 70.03 = 30.040000000000006
        ),
        Transaction(
            date="03-01-2024",
            narration="0.10 DEPOSIT",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("0.10"),
            running_balance=Decimal("30.14"),
        ),
        Transaction(
            date="04-01-2024",
            narration="0.20 DEPOSIT (0.1 + 0.2 HAZARD)",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("0.20"),
            running_balance=Decimal("30.34"),  # In float: 30.14 + 0.20 = 30.340000000000003
        ),
        Transaction(
            date="05-01-2024",
            narration="CLOSING WITHDRAWAL",
            withdrawal=Decimal("10.34"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("20.00"),
        ),
    ]

    result = validate_balance(transactions)

    assert result.is_valid is True
    assert len(result.discrepancies) == 0
    assert result.total_withdrawals == Decimal("80.37")
    assert result.total_deposits == Decimal("0.30")
    assert all(tx.discrepancy is None for tx in result.transactions)


def test_transaction_model_deserializes_strings_to_decimal() -> None:
    tx = Transaction.model_validate({
        "date": "01-01-2024",
        "narration": "STRING PARSING TEST",
        "withdrawal": "123.45",
        "deposit": "0.00",
        "running_balance": "987.65",
    })

    assert isinstance(tx.withdrawal, Decimal)
    assert tx.withdrawal == Decimal("123.45")
    assert isinstance(tx.deposit, Decimal)
    assert tx.deposit == Decimal("0.00")
    assert isinstance(tx.running_balance, Decimal)
    assert tx.running_balance == Decimal("987.65")



def test_empty_transaction_list() -> None:
    result = validate_balance([])

    assert result.is_valid is True
    assert result.total_withdrawals == Decimal("0.00")
    assert result.total_deposits == Decimal("0.00")
    assert result.transactions == []
    assert result.discrepancies == []







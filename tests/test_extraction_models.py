from decimal import Decimal
import bank_statement.models as models
from bank_statement.extractor import ExtractedPage, ExtractedTransaction
from bank_statement.models import Transaction


def test_domain_models_module_does_not_contain_extraction_dtos() -> None:
    assert not hasattr(models, "ExtractedTransaction")
    assert not hasattr(models, "ExtractedPage")
    assert not hasattr(models, "_clean_monetary_amount")
    assert set(models.__all__) == {"Transaction", "Discrepancy", "ValidationResult"}


def test_extracted_transaction_defaults_empty_withdrawal_deposit() -> None:
    raw = ExtractedTransaction(
        date="15-01-2024",
        narration="SALARY CREDIT",
        chq_ref_no=None,
        deposit="50,000.00",
        balance="1,50,000.00",
    )

    assert raw.withdrawal == "0.00"
    domain_tx = raw.to_domain_transaction()
    assert isinstance(domain_tx, Transaction)
    assert domain_tx.withdrawal == Decimal("0.00")
    assert domain_tx.deposit == Decimal("50000.00")
    assert domain_tx.running_balance == Decimal("150000.00")
    assert domain_tx.date == "15-01-2024"
    assert domain_tx.narration == "SALARY CREDIT"
    assert domain_tx.chq_ref_no is None


def test_extracted_transaction_cleans_formatted_currency_and_dashes() -> None:
    raw = ExtractedTransaction(
        date="16-01-2024",
        narration="ATM CASH WITHDRAWAL",
        chq_ref_no="ATM-98712",
        withdrawal=" 2,500.50 ",
        deposit="-",
        balance="1,47,499.50",
    )

    domain_tx = raw.to_domain_transaction()
    assert domain_tx.withdrawal == Decimal("2500.50")
    assert domain_tx.deposit == Decimal("0.00")
    assert domain_tx.running_balance == Decimal("147499.50")
    assert domain_tx.chq_ref_no == "ATM-98712"


def test_extracted_page_deserialization_and_conversion() -> None:
    json_data = """{
        "transactions": [
            {
                "date": "01-01-2024",
                "narration": "OPENING BALANCE",
                "chq_ref_no": null,
                "withdrawal": "0.00",
                "deposit": "1000.00",
                "balance": "1000.00"
            },
            {
                "date": "02-01-2024",
                "narration": "BILL PAYMENT",
                "chq_ref_no": "REF123",
                "withdrawal": "250.00",
                "deposit": "0.00",
                "balance": "750.00"
            }
        ]
    }"""

    page = ExtractedPage.model_validate_json(json_data)
    domain_transactions = [t.to_domain_transaction() for t in page.transactions]

    assert len(domain_transactions) == 2
    assert domain_transactions[0].running_balance == Decimal("1000.00")
    assert domain_transactions[1].withdrawal == Decimal("250.00")
    assert domain_transactions[1].running_balance == Decimal("750.00")


def test_extracted_transaction_cleans_cr_dr_and_accounting_parentheses() -> None:
    raw_cr = ExtractedTransaction(
        date="01-01-2024",
        narration="CREDIT ROW",
        withdrawal="0.00",
        deposit="500.00",
        balance="15,000.00 (Cr)",
    )
    assert raw_cr.to_domain_transaction().running_balance == Decimal("15000.00")

    raw_dr = ExtractedTransaction(
        date="02-01-2024",
        narration="OVERDRAFT ROW",
        withdrawal="200.00",
        deposit="0.00",
        balance="250.00 Dr",
    )
    assert raw_dr.to_domain_transaction().running_balance == Decimal("-250.00")

    raw_paren = ExtractedTransaction(
        date="03-01-2024",
        narration="NEGATIVE BALANCE",
        withdrawal="0.00",
        deposit="0.00",
        balance="(1,200.50)",
    )
    assert raw_paren.to_domain_transaction().running_balance == Decimal("-1200.50")

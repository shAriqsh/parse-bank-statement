import json
from decimal import Decimal
from pathlib import Path
import pytest
from bank_statement.models import (
    BatchValidationResult,
    Discrepancy,
    StatementResult,
    Transaction,
    ValidationResult,
)
from bank_statement.reporter import (
    export_batch_json,
    export_transactions_json,
    format_cli_summary,
)


def test_export_transactions_json_writes_expected_structure_and_values(tmp_path: Path) -> None:
    output_file = tmp_path / "transactions.json"

    tx1 = Transaction(
        date="01-01-2024",
        narration="SALARY CREDIT",
        chq_ref_no="REF123",
        withdrawal=Decimal("0.00"),
        deposit=Decimal("5000.00"),
        running_balance=Decimal("5000.00"),
    )
    discrepancy = Discrepancy(
        expected_balance=Decimal("4500.00"),
        stated_balance=Decimal("4600.00"),
        delta=Decimal("100.00"),
    )
    tx2 = Transaction(
        date="02-01-2024",
        narration="GROCERY STORE",
        chq_ref_no=None,
        withdrawal=Decimal("500.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("4600.00"),
        discrepancy=discrepancy,
    )

    result = ValidationResult(
        transactions=[tx1, tx2],
        total_withdrawals=Decimal("500.00"),
        total_deposits=Decimal("5000.00"),
        discrepancies=[tx2],
        is_valid=False,
    )

    export_transactions_json(result, output_file)

    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))

    assert data["summary"]["total_withdrawals"] == "500.00"
    assert data["summary"]["total_deposits"] == "5000.00"
    assert data["summary"]["transaction_count"] == 2
    assert data["summary"]["discrepancy_count"] == 1
    assert data["summary"]["is_valid"] is False

    assert len(data["transactions"]) == 2
    assert data["transactions"][0]["narration"] == "SALARY CREDIT"
    assert data["transactions"][0]["chq_ref_no"] == "REF123"
    assert data["transactions"][0]["withdrawal"] == "0.00"
    assert data["transactions"][0]["deposit"] == "5000.00"
    assert data["transactions"][0]["running_balance"] == "5000.00"
    assert data["transactions"][0]["discrepancy"] is None

    assert data["transactions"][1]["narration"] == "GROCERY STORE"
    assert data["transactions"][1]["discrepancy"] == {
        "expected_balance": "4500.00",
        "stated_balance": "4600.00",
        "delta": "100.00",
    }

    assert len(data["discrepancies"]) == 1
    assert data["discrepancies"][0]["narration"] == "GROCERY STORE"


def test_format_cli_summary_clean_run_without_discrepancies() -> None:
    tx = Transaction(
        date="01-01-2024",
        narration="OPENING BALANCE",
        withdrawal=Decimal("0.00"),
        deposit=Decimal("1000.00"),
        running_balance=Decimal("1000.00"),
    )
    result = ValidationResult(
        transactions=[tx],
        total_withdrawals=Decimal("0.00"),
        total_deposits=Decimal("1000.00"),
        discrepancies=[],
        is_valid=True,
    )

    summary = format_cli_summary(result)

    assert "Total Withdrawals: INR 0.00" in summary
    assert "Total Deposits:    INR 1,000.00" in summary
    assert "Transactions Parsed: 1" in summary
    assert "Flagged Discrepancies: 0" in summary
    assert "DISCREPANCY DIAGNOSTICS" not in summary


def test_format_cli_summary_with_discrepancy_table() -> None:
    tx_error = Transaction(
        date="15-01-2024",
        narration="ATM CASH WITHDRAWAL #9876",
        withdrawal=Decimal("500.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("600.00"),
        discrepancy=Discrepancy(
            expected_balance=Decimal("500.00"),
            stated_balance=Decimal("600.00"),
            delta=Decimal("100.00"),
        ),
    )
    result = ValidationResult(
        transactions=[tx_error],
        total_withdrawals=Decimal("500.00"),
        total_deposits=Decimal("0.00"),
        discrepancies=[tx_error],
        is_valid=False,
    )

    summary = format_cli_summary(result)

    assert "Total Withdrawals: INR 500.00" in summary
    assert "Total Deposits:    INR 0.00" in summary
    assert "Transactions Parsed: 1" in summary
    assert "Flagged Discrepancies: 1" in summary
    assert "DISCREPANCY DIAGNOSTICS" in summary
    assert "15-01-2024" in summary
    assert "ATM CASH WITHDRAWAL #9876" in summary
    assert "600.00" in summary
    assert "500.00" in summary
    assert "100.00" in summary


def test_export_batch_json_writes_consolidated_batch_schema(tmp_path: Path) -> None:
    output_file = tmp_path / "batch_report.json"

    tx1 = Transaction(
        date="01-01-2024",
        narration="SALARY",
        withdrawal=Decimal("0.00"),
        deposit=Decimal("5000.00"),
        running_balance=Decimal("5000.00"),
    )
    discrepancy = Discrepancy(
        expected_balance=Decimal("4500.00"),
        stated_balance=Decimal("4600.00"),
        delta=Decimal("100.00"),
    )
    tx2 = Transaction(
        date="02-01-2024",
        narration="ONLINE STORE",
        withdrawal=Decimal("500.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("4600.00"),
        discrepancy=discrepancy,
    )
    res1 = ValidationResult(
        transactions=[tx1, tx2],
        total_withdrawals=Decimal("500.00"),
        total_deposits=Decimal("5000.00"),
        discrepancies=[tx2],
        is_valid=False,
    )
    stmt1 = StatementResult(
        pdf_path=Path("january.pdf"),
        status="success",
        result=res1,
        error=None,
    )
    stmt2 = StatementResult(
        pdf_path=Path("corrupted.pdf"),
        status="failed",
        result=None,
        error="Corrupted PDF file header",
    )

    batch_result = BatchValidationResult(
        total_statements=2,
        successful_count=1,
        failed_count=1,
        cumulative_withdrawals=Decimal("500.00"),
        cumulative_deposits=Decimal("5000.00"),
        total_discrepancies=1,
        is_valid=False,
        statements=[stmt1, stmt2],
    )

    export_batch_json(batch_result, output_file)

    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))

    # Assert high-level batch summary
    assert "batch_summary" in data
    assert data["batch_summary"]["total_statements"] == 2
    assert data["batch_summary"]["successful_count"] == 1
    assert data["batch_summary"]["failed_count"] == 1
    assert data["batch_summary"]["cumulative_withdrawals"] == "500.00"
    assert data["batch_summary"]["cumulative_deposits"] == "5000.00"
    assert data["batch_summary"]["total_discrepancies"] == 1
    assert data["batch_summary"]["is_valid"] is False

    # Assert statements
    assert "statements" in data
    assert len(data["statements"]) == 2

    # Successful statement verification
    s1_data = data["statements"][0]
    assert s1_data["pdf_path"] == "january.pdf"
    assert s1_data["status"] == "success"
    assert s1_data["error"] is None
    assert s1_data["summary"]["total_withdrawals"] == "500.00"
    assert s1_data["summary"]["total_deposits"] == "5000.00"
    assert s1_data["summary"]["transaction_count"] == 2
    assert s1_data["summary"]["discrepancy_count"] == 1
    assert s1_data["summary"]["is_valid"] is False
    assert len(s1_data["transactions"]) == 2
    assert len(s1_data["discrepancies"]) == 1

    # Failed statement verification
    s2_data = data["statements"][1]
    assert s2_data["pdf_path"] == "corrupted.pdf"
    assert s2_data["status"] == "failed"
    assert s2_data["summary"] is None
    assert s2_data["transactions"] == []
    assert s2_data["discrepancies"] == []
    assert s2_data["error"] == "Corrupted PDF file header"


def test_export_batch_json_writes_individual_files_to_output_dir(tmp_path: Path) -> None:
    output_file = tmp_path / "batch.json"
    out_dir = tmp_path / "individual_statements"

    tx = Transaction(
        date="10-02-2024",
        narration="DIVIDEND CREDIT",
        withdrawal=Decimal("0.00"),
        deposit=Decimal("1200.00"),
        running_balance=Decimal("1200.00"),
    )
    res = ValidationResult(
        transactions=[tx],
        total_withdrawals=Decimal("0.00"),
        total_deposits=Decimal("1200.00"),
        discrepancies=[],
        is_valid=True,
    )
    stmt_success = StatementResult(
        pdf_path=Path("statements/q1_statement.pdf"),
        status="success",
        result=res,
        error=None,
    )
    stmt_fail = StatementResult(
        pdf_path=Path("statements/q2_broken.pdf"),
        status="failed",
        result=None,
        error="Extraction timed out",
    )
    batch_result = BatchValidationResult(
        total_statements=2,
        successful_count=1,
        failed_count=1,
        cumulative_withdrawals=Decimal("0.00"),
        cumulative_deposits=Decimal("1200.00"),
        total_discrepancies=0,
        is_valid=False,
        statements=[stmt_success, stmt_fail],
    )

    export_batch_json(batch_result, output_file, output_dir=out_dir)

    assert output_file.exists()
    assert out_dir.exists()

    # Successful statement wrote individual <stem>_transactions.json
    stmt_file = out_dir / "q1_statement_transactions.json"
    assert stmt_file.exists()
    stmt_data = json.loads(stmt_file.read_text(encoding="utf-8"))
    assert stmt_data["summary"]["transaction_count"] == 1
    assert stmt_data["summary"]["total_deposits"] == "1200.00"
    assert len(stmt_data["transactions"]) == 1
    assert stmt_data["transactions"][0]["narration"] == "DIVIDEND CREDIT"

    # Failed statement should NOT have generated an individual file
    fail_file = out_dir / "q2_broken_transactions.json"
    assert not fail_file.exists()


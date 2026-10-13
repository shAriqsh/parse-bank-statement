import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from bank_statement.cli import main
from bank_statement.models import Discrepancy, Transaction, ValidationResult


@pytest.fixture
def mock_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock get_gemini_client so it doesn't require real API key in tests
    mock_client = MagicMock()
    monkeypatch.setattr("bank_statement.cli.get_gemini_client", lambda: mock_client)


def test_main_runs_pipeline_exports_json_and_prints_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_json = tmp_path / "transactions.json"
    dummy_pdf = tmp_path / "test_statement.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

    sample_txs = [
        Transaction(
            date="01-01-2024",
            narration="SALARY",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("10000.00"),
            running_balance=Decimal("10000.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="RENT PAYMENT",
            withdrawal=Decimal("2000.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("8000.00"),
        ),
    ]

    async def mock_parse_statement(pdf_path: object, **kwargs: object) -> ValidationResult:
        return ValidationResult(
            transactions=sample_txs,
            total_withdrawals=Decimal("2000.00"),
            total_deposits=Decimal("10000.00"),
            discrepancies=[],
            is_valid=True,
        )

    monkeypatch.setattr("bank_statement.cli.parse_statement", mock_parse_statement)

    exit_code = main([str(dummy_pdf), "--output", str(output_json)])

    assert exit_code == 0

    # Verify stdout output
    captured = capsys.readouterr()
    assert "BANK STATEMENT SUMMARY" in captured.out
    assert "Total Withdrawals: INR 2,000.00" in captured.out
    assert "Total Deposits:    INR 10,000.00" in captured.out
    assert "Transactions Parsed: 2" in captured.out
    assert "Flagged Discrepancies: 0" in captured.out

    # Verify transactions.json artifact was created and populated
    assert output_json.exists()
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["summary"]["total_withdrawals"] == "2000.00"
    assert data["summary"]["total_deposits"] == "10000.00"
    assert data["summary"]["transaction_count"] == 2
    assert data["summary"]["is_valid"] is True
    assert len(data["transactions"]) == 2


def test_main_with_discrepancies_prints_diagnostic_table(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_json = tmp_path / "transactions.json"
    dummy_pdf = tmp_path / "test_statement.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

    tx_mismatch = Transaction(
        date="05-01-2024",
        narration="ONLINE PURCHASE",
        withdrawal=Decimal("300.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("9000.00"),
        discrepancy=Discrepancy(
            expected_balance=Decimal("9700.00"),
            stated_balance=Decimal("9000.00"),
            delta=Decimal("-700.00"),
        ),
    )

    async def mock_parse_statement(pdf_path: object, **kwargs: object) -> ValidationResult:
        return ValidationResult(
            transactions=[tx_mismatch],
            total_withdrawals=Decimal("300.00"),
            total_deposits=Decimal("0.00"),
            discrepancies=[tx_mismatch],
            is_valid=False,
        )

    monkeypatch.setattr("bank_statement.cli.parse_statement", mock_parse_statement)

    exit_code = main([str(dummy_pdf), "--output", str(output_json)])

    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Flagged Discrepancies: 1" in captured.out
    assert "DISCREPANCY DIAGNOSTICS" in captured.out
    assert "ONLINE PURCHASE" in captured.out
    assert "9000.00" in captured.out
    assert "9700.00" in captured.out
    assert "-700.00" in captured.out

    assert output_json.exists()
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert data["summary"]["discrepancy_count"] == 1
    assert data["summary"]["is_valid"] is False
    assert len(data["discrepancies"]) == 1


def test_main_missing_pdf_returns_error(
    capsys: pytest.CaptureFixture[str],
    mock_pipeline: None,
) -> None:
    exit_code = main(["non_existent_file.pdf"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Error: Bank statement file not found" in captured.out


def test_main_script_runs_as_main(
    tmp_path: Path,
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runpy

    main_py_path = Path(__file__).resolve().parent.parent / "main.py"
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy")
    output_json = tmp_path / "out.json"

    async def mock_parse_statement(pdf_path: object, **kwargs: object) -> ValidationResult:
        return ValidationResult(
            transactions=[],
            total_withdrawals=Decimal("0.00"),
            total_deposits=Decimal("0.00"),
            discrepancies=[],
            is_valid=True,
        )

    monkeypatch.setattr("bank_statement.cli.parse_statement", mock_parse_statement)
    monkeypatch.setattr("sys.argv", ["main.py", str(dummy_pdf), "-o", str(output_json)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(main_py_path), run_name="__main__")

    assert exc_info.value.code == 0
    assert output_json.exists()

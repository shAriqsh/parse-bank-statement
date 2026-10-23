from collections.abc import Sequence
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
from bank_statement.cli import main, resolve_pdf_paths
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


def test_resolve_pdf_paths_with_existing_files(tmp_path: Path) -> None:
    f1 = tmp_path / "january.pdf"
    f2 = tmp_path / "february.PDF"
    f1.write_bytes(b"%PDF dummy1")
    f2.write_bytes(b"%PDF dummy2")

    resolved = resolve_pdf_paths([str(f1), f2])
    assert resolved == [f1, f2]


def test_resolve_pdf_paths_with_directory_discovery_sorted(tmp_path: Path) -> None:
    dir_path = tmp_path / "statements"
    dir_path.mkdir()
    f_c = dir_path / "c_statement.pdf"
    f_a = dir_path / "a_statement.PDF"
    f_b = dir_path / "b_statement.pdf"
    txt = dir_path / "notes.txt"

    f_c.write_bytes(b"%PDF dummy c")
    f_a.write_bytes(b"%PDF dummy a")
    f_b.write_bytes(b"%PDF dummy b")
    txt.write_text("not a pdf")

    resolved = resolve_pdf_paths([str(dir_path)])
    assert resolved == [f_a, f_b, f_c]


def test_resolve_pdf_paths_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    missing_file = tmp_path / "ghost.pdf"
    with pytest.raises(FileNotFoundError, match="ghost.pdf"):
        resolve_pdf_paths([missing_file])


def test_resolve_pdf_paths_empty_directory_raises_valueerror(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    (empty_dir / "readme.txt").write_text("no pdfs here")

    with pytest.raises(ValueError, match="contains zero PDF files"):
        resolve_pdf_paths([empty_dir])


def test_main_multiple_pdf_arguments_passes_to_batch_pipeline(
    tmp_path: Path,
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f1 = tmp_path / "jan.pdf"
    f2 = tmp_path / "feb.pdf"
    f1.write_bytes(b"%PDF dummy 1")
    f2.write_bytes(b"%PDF dummy 2")

    batch_called_with: list[Path] = []

    async def mock_batch(paths: Any, **kwargs: object) -> MagicMock:
        nonlocal batch_called_with
        batch_called_with = list(paths)
        mock_res = MagicMock()
        mock_res.is_valid = True
        return mock_res

    monkeypatch.setattr("bank_statement.cli.parse_batch_statements", mock_batch)

    exit_code = main([str(f1), str(f2)])
    assert exit_code == 0
    assert batch_called_with == [f1, f2]


def test_main_directory_argument_discovers_pdfs_and_runs_batch(
    tmp_path: Path,
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dir_path = tmp_path / "batch_folder"
    dir_path.mkdir()
    f2 = dir_path / "02.pdf"
    f1 = dir_path / "01.pdf"
    f2.write_bytes(b"%PDF 2")
    f1.write_bytes(b"%PDF 1")

    batch_called_with: list[Path] = []

    async def mock_batch(paths: Any, **kwargs: object) -> MagicMock:
        nonlocal batch_called_with
        batch_called_with = list(paths)
        mock_res = MagicMock()
        mock_res.is_valid = True
        return mock_res

    monkeypatch.setattr("bank_statement.cli.parse_batch_statements", mock_batch)

    exit_code = main([str(dir_path)])
    assert exit_code == 0
    assert batch_called_with == [f1, f2]


def test_main_empty_directory_halts_with_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mock_pipeline: None,
) -> None:
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    exit_code = main([str(empty_dir)])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "contains zero PDF files" in captured.out


def test_main_missing_file_in_multi_arg_halts_immediately(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f1 = tmp_path / "valid.pdf"
    f1.write_bytes(b"%PDF valid")

    pipeline_invoked = False

    async def mock_batch(*args: object, **kwargs: object) -> MagicMock:
        nonlocal pipeline_invoked
        pipeline_invoked = True
        return MagicMock()

    monkeypatch.setattr("bank_statement.cli.parse_batch_statements", mock_batch)

    exit_code = main([str(f1), str(tmp_path / "missing.pdf")])
    assert exit_code == 1
    assert not pipeline_invoked

    captured = capsys.readouterr()
    assert "Error: Bank statement file not found" in captured.out


def test_main_default_argument_uses_account_pdf(
    mock_pipeline: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called_with: list[object] = []

    def mock_resolve(inputs: Sequence[str | Path]) -> list[Path]:
        called_with.extend(inputs)
        return [Path("account.pdf")]

    async def mock_parse_stmt(*args: object, **kwargs: object) -> ValidationResult:
        return ValidationResult(
            transactions=[],
            total_withdrawals=Decimal("0.00"),
            total_deposits=Decimal("0.00"),
            discrepancies=[],
            is_valid=True,
        )

    def mock_export(*args: object, **kwargs: object) -> None:
        pass

    def mock_summary(*args: object, **kwargs: object) -> str:
        return ""

    monkeypatch.setattr("bank_statement.cli.resolve_pdf_paths", mock_resolve)
    monkeypatch.setattr("bank_statement.cli.parse_statement", mock_parse_stmt)
    monkeypatch.setattr("bank_statement.cli.export_transactions_json", mock_export)
    monkeypatch.setattr("bank_statement.cli.format_cli_summary", mock_summary)

    exit_code = main([])
    assert exit_code == 0
    assert called_with == ["account.pdf"]

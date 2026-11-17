from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
from streamlit.testing.v1 import AppTest
from bank_statement.models import Discrepancy, Transaction, ValidationResult


APP_PATH = str(Path(__file__).resolve().parent.parent / "src" / "bank_statement" / "ui" / "app.py")


@pytest.fixture
def sample_valid_result() -> ValidationResult:
    txs = [
        Transaction(
            date="01-01-2024",
            narration="SALARY CREDIT",
            chq_ref_no="CR123",
            withdrawal=Decimal("0.00"),
            deposit=Decimal("10000.00"),
            running_balance=Decimal("10000.00"),
        ),
        Transaction(
            date="02-01-2024",
            narration="RENT PAYMENT",
            chq_ref_no="CHQ456",
            withdrawal=Decimal("2000.00"),
            deposit=Decimal("0.00"),
            running_balance=Decimal("8000.00"),
        ),
    ]
    return ValidationResult(
        transactions=txs,
        total_withdrawals=Decimal("2000.00"),
        total_deposits=Decimal("10000.00"),
        discrepancies=[],
        is_valid=True,
    )


@pytest.fixture
def sample_discrepancy_result() -> ValidationResult:
    tx_bad = Transaction(
        date="03-01-2024",
        narration="UTILITY BILL",
        chq_ref_no="BILL789",
        withdrawal=Decimal("500.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("7000.00"),  # Expected: 7500.00, stated: 7000.00
        discrepancy=Discrepancy(
            expected_balance=Decimal("7500.00"),
            stated_balance=Decimal("7000.00"),
            delta=Decimal("-500.00"),
        ),
    )
    return ValidationResult(
        transactions=[tx_bad],
        total_withdrawals=Decimal("500.00"),
        total_deposits=Decimal("0.00"),
        discrepancies=[tx_bad],
        is_valid=False,
    )


def test_ui_initial_landing_prompts_for_upload() -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not at.exception
    assert len(at.title) >= 1
    assert "Bank Statement" in at.title[0].value
    assert len(at.file_uploader) == 1
    # Info prompt to upload is present
    assert len(at.info) >= 1
    assert "drag and drop" in at.info[0].value.lower() or "upload" in at.info[0].value.lower()
    # Metrics and tables should not be rendered before upload
    assert len(at.metric) == 0
    assert len(at.dataframe) == 0


def test_ui_upload_statement_renders_metrics_and_ledger(
    monkeypatch: pytest.MonkeyPatch,
    sample_valid_result: ValidationResult,
) -> None:
    seen_temp_paths: list[Path] = []

    async def mock_parse_statement(path: str | Path, **kwargs: Any) -> ValidationResult:
        p = Path(path)
        seen_temp_paths.append(p)
        assert p.exists(), "Temporary file should exist during parse_statement execution"
        cb = kwargs.get("progress_callback")
        if cb:
            cb("Processing pages...", 0.5)
        return sample_valid_result

    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse_statement)
    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse_statement)

    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert len(at.file_uploader) == 1

    # Upload single statement PDF
    at.file_uploader[0].upload("sample_statement.pdf", b"%PDF-1.4 dummy statement content", "application/pdf").run()
    assert not at.exception

    # Verify temp file was cleaned up immediately after extraction
    assert len(seen_temp_paths) == 1
    assert not seen_temp_paths[0].exists(), "Temporary file must be deleted immediately after extraction"

    # Verify 4 summary metric cards
    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    assert any("withdrawal" in l.lower() for l in labels)
    assert any("deposit" in l.lower() for l in labels)
    assert any("transaction" in l.lower() for l in labels)
    assert any("valid" in l.lower() or "integrity" in l.lower() or "status" in l.lower() for l in labels)

    assert any("2,000.00" in str(v) for v in values)
    assert any("10,000.00" in str(v) for v in values)
    assert any("2" == str(v).strip() for v in values)
    assert any("valid" in str(v).lower() for v in values)

    # Verify chronological transaction dataframe
    assert len(at.dataframe) >= 1
    df = at.dataframe[0].value
    assert len(df) == 2
    assert "SALARY CREDIT" in df["Narration"].values
    assert "RENT PAYMENT" in df["Narration"].values


def test_ui_session_state_caching_prevents_reextraction(
    monkeypatch: pytest.MonkeyPatch,
    sample_valid_result: ValidationResult,
) -> None:
    extraction_count = 0

    async def mock_parse(path: str | Path, **kwargs: Any) -> ValidationResult:
        nonlocal extraction_count
        extraction_count += 1
        return sample_valid_result

    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse)
    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse)

    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    at.file_uploader[0].upload("cached_statement.pdf", b"%PDF-1.4 dummy", "application/pdf").run()
    assert not at.exception
    assert extraction_count == 1

    # Trigger second run / re-render
    at.run()
    assert not at.exception
    # Should still be 1, because result was cached in session state!
    assert extraction_count == 1
    # Metrics are still rendered
    assert len(at.metric) >= 4


def test_ui_upload_statement_with_discrepancy(
    monkeypatch: pytest.MonkeyPatch,
    sample_discrepancy_result: ValidationResult,
) -> None:
    async def mock_parse(path: str | Path, **kwargs: Any) -> ValidationResult:
        return sample_discrepancy_result

    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse)
    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse)

    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    at.file_uploader[0].upload("discrepant.pdf", b"%PDF-1.4 dummy", "application/pdf").run()
    assert not at.exception

    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    # Verification status metric reflects discrepancy
    status_values = [v for l, v in zip(labels, values) if "valid" in l.lower() or "integrity" in l.lower() or "status" in l.lower()]
    assert any("discrepanc" in str(v).lower() or "flagged" in str(v).lower() or "invalid" in str(v).lower() for v in status_values)

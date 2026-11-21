from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
from streamlit.testing.v1 import AppTest
from bank_statement.models import BatchValidationResult, Discrepancy, StatementResult, Transaction, ValidationResult
from bank_statement.ui.components import (
    HIGHLIGHT_ROW_STYLE,
    build_styled_transaction_table,
    get_statement_tab_label,
    render_batch_summary_banner,
    render_batch_tabs,
    render_discrepancy_diagnostics,
    render_summary_metrics,
    render_transaction_table,
)


APP_PATH = str(Path(__file__).resolve().parent.parent / "src" / "bank_statement" / "ui" / "app.py")
DEFAULT_TIMEOUT = 10


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


# ===========================================================================
# Tier 2: End-to-End App Integration Tests (via AppTest.from_file)
# ===========================================================================

def test_ui_initial_landing_prompts_for_upload() -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
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

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse_statement)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse_statement)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
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

    assert any("2,000.00" in v for v in values)
    assert any("10,000.00" in v for v in values)
    assert any("2" == v for v in values)
    assert any("valid" in v.lower() for v in values)

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

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
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


def test_ui_upload_statement_with_discrepancy_renders_alert_card_and_highlighted_table(
    monkeypatch: pytest.MonkeyPatch,
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    """Full-app headless integration test: uploading statement with discrepancies renders alert and flags rows."""
    async def mock_parse_statement(path: str | Path, **kwargs: Any) -> ValidationResult:
        return multi_tx_discrepancy_result

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse_statement)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse_statement)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
    at.file_uploader[0].upload("discrepant_statement.pdf", b"%PDF-1.4 dummy", "application/pdf").run()
    assert not at.exception

    # Prominent Discrepancy Alert card is displayed with variance details
    all_text = _collect_rendered_text(at)
    assert "Discrepancy Alert" in all_text
    assert "02-01-2024" in all_text
    assert "9,500.00" in all_text
    assert "9,000.00" in all_text
    assert "500.00" in all_text
    assert "re-anchor" in all_text.lower()

    # Ledger dataframe renders all transactions
    assert len(at.dataframe) >= 1
    df = at.dataframe[0].value
    assert len(df) == 3
    assert "UTILITY BILL" in df["Narration"].values


def test_ui_upload_multi_statement_batch_renders_summary_banner_and_tabs(
    monkeypatch: pytest.MonkeyPatch,
    sample_valid_result: ValidationResult,
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    seen_temp_paths: list[Path] = []

    async def mock_parse_statement(pdf_path: str | Path, **kwargs: Any) -> ValidationResult:
        p = Path(pdf_path)
        seen_temp_paths.append(p)
        assert p.exists(), "Temporary file should exist during parse_statement execution"
        if "statement_1" in p.name:
            return sample_valid_result
        return multi_tx_discrepancy_result

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse_statement)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse_statement)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
    assert len(at.file_uploader) == 1

    # Upload two statement PDFs concurrently
    at.file_uploader[0].upload(
        "statement_1.pdf", b"%PDF-1.4 file 1", "application/pdf"
    ).upload(
        "statement_2.pdf", b"%PDF-1.4 file 2", "application/pdf"
    ).run()
    assert not at.exception

    # Verify temp files were cleaned up immediately after extraction
    assert len(seen_temp_paths) == 2
    for p in seen_temp_paths:
        assert not p.exists(), f"Temporary file {p} must be deleted immediately after extraction"

    # Verify batch summary banner metrics
    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    assert any("statement" in l.lower() for l in labels)
    assert any("2" in v for v in values)
    assert any("cumulative" in l.lower() and "withdrawal" in l.lower() for l in labels)
    assert any("2,700.00" in v for v in values)
    assert any("cumulative" in l.lower() and "deposit" in l.lower() for l in labels)
    assert any("20,000.00" in v for v in values)

    # Verify dedicated tabs
    assert len(at.tabs) == 2
    all_text = _collect_rendered_text(at)
    assert "statement_1.pdf" in all_text
    assert "statement_2.pdf" in all_text

    # Verify both transaction dataframes exist
    assert len(at.dataframe) == 2


def test_ui_upload_multi_statement_batch_isolates_statement_failure(
    monkeypatch: pytest.MonkeyPatch,
    sample_valid_result: ValidationResult,
) -> None:
    seen_temp_paths: list[Path] = []

    async def mock_parse_statement(pdf_path: str | Path, **kwargs: Any) -> ValidationResult:
        p = Path(pdf_path)
        seen_temp_paths.append(p)
        if "bad_statement" in p.name:
            raise ValueError("Corrupt PDF structure")
        return sample_valid_result

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse_statement)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse_statement)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
    at.file_uploader[0].upload(
        "good_statement.pdf", b"%PDF-1.4 good", "application/pdf"
    ).upload(
        "bad_statement.pdf", b"%PDF-1.4 bad", "application/pdf"
    ).run()
    assert not at.exception

    # Temp files cleaned up
    assert len(seen_temp_paths) == 2
    for p in seen_temp_paths:
        assert not p.exists()

    # Batch summary banner reflects 1 failed statement without crashing
    all_text = _collect_rendered_text(at)
    assert "Batch Issues Flagged" in all_text or "1 of 2" in all_text or "failed" in all_text.lower()

    # Tabs rendered for both statements
    assert len(at.tabs) == 2

    # Diagnostic error message isolated to the bad statement tab
    assert "Corrupt PDF structure" in all_text
    assert len(at.error) >= 1

    # Successful statement still has its transaction ledger
    assert len(at.dataframe) == 1
    df = at.dataframe[0].value
    assert "SALARY CREDIT" in df["Narration"].values


def test_ui_batch_session_state_caching_prevents_reextraction(
    monkeypatch: pytest.MonkeyPatch,
    sample_valid_result: ValidationResult,
) -> None:
    extraction_count = 0

    async def mock_parse(pdf_path: str | Path, **kwargs: Any) -> ValidationResult:
        nonlocal extraction_count
        extraction_count += 1
        return sample_valid_result

    monkeypatch.setattr("bank_statement.ui.app.parse_statement", mock_parse)
    monkeypatch.setattr("bank_statement.orchestrator.parse_statement", mock_parse)

    at = AppTest.from_file(APP_PATH, default_timeout=DEFAULT_TIMEOUT).run()
    at.file_uploader[0].upload(
        "s1.pdf", b"%PDF-1.4 f1", "application/pdf"
    ).upload(
        "s2.pdf", b"%PDF-1.4 f2", "application/pdf"
    ).run()
    assert not at.exception
    assert extraction_count == 2

    # Rerun / user interaction without re-uploading
    at.run()
    assert not at.exception
    # Should not re-extract
    assert extraction_count == 2
    assert len(at.tabs) == 2


# ===========================================================================
# Tier 1: Component Unit Tests (Fast & Isolated via AppTest.from_function)
# ===========================================================================

def test_ui_upload_statement_with_discrepancy_metric(
    sample_discrepancy_result: ValidationResult,
) -> None:
    """Verification status metric reflects discrepancy."""
    at = AppTest.from_function(
        render_summary_metrics,
        args=(sample_discrepancy_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    # Verification status metric reflects discrepancy
    status_values = [v for l, v in zip(labels, values) if "valid" in l.lower() or "integrity" in l.lower() or "status" in l.lower()]
    assert any("discrepanc" in v.lower() or "flagged" in v.lower() or "invalid" in v.lower() for v in status_values)


@pytest.fixture
def multi_tx_discrepancy_result() -> ValidationResult:
    """Result with a mix of clean and discrepant transactions for row highlighting tests."""
    tx_clean = Transaction(
        date="01-01-2024",
        narration="SALARY CREDIT",
        chq_ref_no="CR123",
        withdrawal=Decimal("0.00"),
        deposit=Decimal("10000.00"),
        running_balance=Decimal("10000.00"),
    )
    tx_bad = Transaction(
        date="02-01-2024",
        narration="UTILITY BILL",
        chq_ref_no="BILL789",
        withdrawal=Decimal("500.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("9000.00"),  # Expected: 9500.00
        discrepancy=Discrepancy(
            expected_balance=Decimal("9500.00"),
            stated_balance=Decimal("9000.00"),
            delta=Decimal("-500.00"),
        ),
    )
    tx_after = Transaction(
        date="03-01-2024",
        narration="GROCERIES",
        chq_ref_no=None,
        withdrawal=Decimal("200.00"),
        deposit=Decimal("0.00"),
        running_balance=Decimal("8800.00"),
    )
    return ValidationResult(
        transactions=[tx_clean, tx_bad, tx_after],
        total_withdrawals=Decimal("700.00"),
        total_deposits=Decimal("10000.00"),
        discrepancies=[tx_bad],
        is_valid=False,
    )


def test_ui_discrepancy_alert_card_rendered(
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    """Prominent Discrepancy Alert card shows mismatch details above the ledger."""
    at = AppTest.from_function(
        render_discrepancy_diagnostics,
        args=(multi_tx_discrepancy_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    # Find warning/error elements that contain discrepancy alert details
    all_text = _collect_rendered_text(at)

    # Must contain the date and variance details of the mismatch
    assert "02-01-2024" in all_text, "Alert card must show the discrepancy transaction date"
    assert "9,500.00" in all_text, "Alert card must show the expected balance"
    assert "9,000.00" in all_text, "Alert card must show the stated running balance"
    assert "500.00" in all_text, "Alert card must show the delta"


def test_ui_discrepancy_alert_mentions_reanchoring(
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    """Alert explicitly notes that sequential balance checking re-anchored."""
    at = AppTest.from_function(
        render_discrepancy_diagnostics,
        args=(multi_tx_discrepancy_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    all_text = _collect_rendered_text(at)
    assert "re-anchor" in all_text.lower(), (
        "Discrepancy alert must explain re-anchoring to stated balance"
    )


def test_ui_discrepancy_rows_highlighted_in_table(
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    """Transaction rows with discrepancies are visually highlighted with distinct styling."""
    txs = multi_tx_discrepancy_result.transactions

    # 1. Verify Styler logic applies highlight style to row 1 (UTILITY BILL) and not row 0 or 2
    styled = build_styled_transaction_table(txs)
    html_output = styled.to_html()

    assert "#fee2e2" in html_output, "Highlight background color must be present in styled table"
    assert "#991b1b" in html_output, "Highlight text color must be present in styled table"
    assert "UTILITY BILL" in html_output

    # 2. Verify headless Streamlit component renders cleanly without error
    at = AppTest.from_function(
        render_transaction_table,
        args=(txs,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception
    assert len(at.dataframe) >= 1
    df = at.dataframe[0].value
    assert len(df) == 3
    assert list(df["Narration"].values) == ["SALARY CREDIT", "UTILITY BILL", "GROCERIES"]


def test_ui_zero_discrepancies_shows_confirmation_badge(
    sample_valid_result: ValidationResult,
) -> None:
    """Statements with zero discrepancies render a visual confirmation badge."""
    at = AppTest.from_function(
        render_discrepancy_diagnostics,
        args=(sample_valid_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    all_text = _collect_rendered_text(at)
    # Should contain a success confirmation (not a discrepancy alert)
    assert "integrity" in all_text.lower() or "verified" in all_text.lower() or "✅" in all_text, (
        "Zero-discrepancy statement must display a confirmation badge"
    )
    assert "discrepancy alert" not in all_text.lower(), (
        "No discrepancy alert should appear for clean statements"
    )

    # Edge case: is_valid=False but 0 discrepancies still renders zero-discrepancy badge
    empty_discrepancy_result = ValidationResult(
        transactions=[],
        total_withdrawals=Decimal("0.00"),
        total_deposits=Decimal("0.00"),
        discrepancies=[],
        is_valid=False,
    )
    at_empty = AppTest.from_function(
        render_discrepancy_diagnostics,
        args=(empty_discrepancy_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at_empty.exception
    all_text_empty = _collect_rendered_text(at_empty)
    assert "integrity" in all_text_empty.lower() or "verified" in all_text_empty.lower()


@pytest.fixture
def sample_clean_batch_result(
    sample_valid_result: ValidationResult,
) -> BatchValidationResult:
    return BatchValidationResult(
        total_statements=2,
        successful_count=2,
        failed_count=0,
        cumulative_withdrawals=Decimal("4000.00"),
        cumulative_deposits=Decimal("20000.00"),
        total_discrepancies=0,
        is_valid=True,
        statements=[
            StatementResult(
                pdf_path=Path("statement_1.pdf"),
                status="success",
                result=sample_valid_result,
            ),
            StatementResult(
                pdf_path=Path("statement_2.pdf"),
                status="success",
                result=sample_valid_result,
            ),
        ],
    )


@pytest.fixture
def sample_mixed_batch_result(
    sample_valid_result: ValidationResult,
    multi_tx_discrepancy_result: ValidationResult,
) -> BatchValidationResult:
    return BatchValidationResult(
        total_statements=3,
        successful_count=2,
        failed_count=1,
        cumulative_withdrawals=Decimal("2700.00"),
        cumulative_deposits=Decimal("20000.00"),
        total_discrepancies=1,
        is_valid=False,
        statements=[
            StatementResult(
                pdf_path=Path("statement_clean.pdf"),
                status="success",
                result=sample_valid_result,
            ),
            StatementResult(
                pdf_path=Path("statement_discrepant.pdf"),
                status="success",
                result=multi_tx_discrepancy_result,
            ),
            StatementResult(
                pdf_path=Path("statement_corrupted.pdf"),
                status="failed",
                error="Invalid PDF header stream",
            ),
        ],
    )


def test_ui_render_batch_summary_banner_clean(
    sample_clean_batch_result: BatchValidationResult,
) -> None:
    at = AppTest.from_function(
        render_batch_summary_banner,
        args=(sample_clean_batch_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    assert any("statement" in l.lower() for l in labels)
    assert any("2" in v for v in values)
    assert any("cumulative" in l.lower() and "withdrawal" in l.lower() for l in labels)
    assert any("4,000.00" in v for v in values)
    assert any("cumulative" in l.lower() and "deposit" in l.lower() for l in labels)
    assert any("20,000.00" in v for v in values)
    assert any("discrepanc" in l.lower() for l in labels)
    assert any("0" in v for v in values)

    all_text = _collect_rendered_text(at)
    assert "batch verification succeeded" in all_text.lower() or "verified" in all_text.lower()


def test_ui_render_batch_summary_banner_with_failures_and_discrepancies(
    sample_mixed_batch_result: BatchValidationResult,
) -> None:
    at = AppTest.from_function(
        render_batch_summary_banner,
        args=(sample_mixed_batch_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    labels = [m.label for m in at.metric]
    values = [m.value for m in at.metric]

    assert any("statement" in l.lower() for l in labels)
    assert any("3" in v for v in values)
    assert any("success" in l.lower() or "fail" in l.lower() for l in labels)
    assert any("2 / 1" in v for v in values)
    assert any("cumulative" in l.lower() and "withdrawal" in l.lower() for l in labels)
    assert any("2,700.00" in v for v in values)
    assert any("cumulative" in l.lower() and "deposit" in l.lower() for l in labels)
    assert any("20,000.00" in v for v in values)
    assert any("discrepanc" in l.lower() for l in labels)
    assert any("1" in v for v in values)

    all_text = _collect_rendered_text(at)
    assert "batch issues flagged" in all_text.lower() or "failed" in all_text.lower()


def test_ui_get_statement_tab_label(
    sample_valid_result: ValidationResult,
    multi_tx_discrepancy_result: ValidationResult,
) -> None:
    valid_stmt = StatementResult(
        pdf_path=Path("january.pdf"),
        status="success",
        result=sample_valid_result,
    )
    discrepant_stmt = StatementResult(
        pdf_path=Path("february.pdf"),
        status="success",
        result=multi_tx_discrepancy_result,
    )
    failed_stmt = StatementResult(
        pdf_path=Path("corrupt.pdf"),
        status="failed",
        error="Extraction timed out",
    )

    label_valid = get_statement_tab_label(valid_stmt)
    assert "january.pdf" in label_valid
    assert "Valid" in label_valid or "✅" in label_valid

    label_discrepant = get_statement_tab_label(discrepant_stmt)
    assert "february.pdf" in label_discrepant
    assert "Discrepanc" in label_discrepant or "⚠️" in label_discrepant

    label_failed = get_statement_tab_label(failed_stmt)
    assert "corrupt.pdf" in label_failed
    assert "Failed" in label_failed or "❌" in label_failed


def test_ui_render_batch_tabs_content_and_isolation(
    sample_mixed_batch_result: BatchValidationResult,
) -> None:
    at = AppTest.from_function(
        render_batch_tabs,
        args=(sample_mixed_batch_result,),
        default_timeout=DEFAULT_TIMEOUT,
    ).run()
    assert not at.exception

    # Check tab existence
    assert len(at.tabs) == 3

    all_text = _collect_rendered_text(at)

    # Clean statement content is present
    assert "statement_clean.pdf" in all_text

    # Discrepant statement content and alert is present
    assert "statement_discrepant.pdf" in all_text

    # Dataframes rendered for the 2 successful statements
    assert len(at.dataframe) == 2
    df_clean = at.dataframe[0].value
    assert "SALARY CREDIT" in df_clean["Narration"].values
    df_discrepant = at.dataframe[1].value
    assert "UTILITY BILL" in df_discrepant["Narration"].values

    # Failed statement diagnostics is present and isolated
    assert "statement_corrupted.pdf" in all_text
    assert "Invalid PDF header stream" in all_text
    assert len(at.error) >= 1


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _collect_rendered_text(at: AppTest) -> str:
    """Gather all visible text from an AppTest run for content assertions."""
    parts: list[str] = []
    for attr in ("title", "header", "subheader", "caption", "text", "markdown",
                 "info", "success", "warning", "error"):
        for el in getattr(at, attr, []):
            parts.append(str(getattr(el, "value", el)))
    return "\n".join(parts)

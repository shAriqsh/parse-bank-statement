from dataclasses import dataclass
from typing import Any, Sequence

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from bank_statement.models import (
    BatchValidationResult,
    StatementResult,
    Transaction,
    ValidationResult,
)
from bank_statement.reporter import (
    format_batch_result_json,
    format_validation_result_json,
)

HIGHLIGHT_ROW_STYLE = "background-color: #fee2e2; color: #991b1b; font-weight: bold"


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime extraction pipeline parameters configured via the sidebar."""

    max_concurrency: int = 5
    max_retries: int = 3
    retry_base_delay: float = 1.0


def render_sidebar_config(api_key_ready: bool) -> RuntimeConfig:
    """Render collapsible runtime configuration sidebar and return selected parameters."""
    with st.sidebar:
        st.header("⚙️ Runtime Configuration")

        st.subheader("Google GenAI API Key")
        if api_key_ready:
            st.success("✅ Configured & Ready")
        else:
            st.warning("⚠️ Not Configured")
            st.caption(
                "Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` in your environment or `.env` file."
            )

        st.divider()
        st.subheader("Extraction Pipeline")

        max_concurrency = st.slider(
            "Max Concurrency",
            min_value=1,
            max_value=20,
            value=5,
            step=1,
            help="Maximum concurrent page extraction workers (default: 5)",
        )
        max_retries = st.slider(
            "Max Retries",
            min_value=0,
            max_value=10,
            value=3,
            step=1,
            help="Maximum retry attempts on transient API errors (default: 3)",
        )
        retry_base_delay = st.slider(
            "Retry Base Delay (s)",
            min_value=0.1,
            max_value=10.0,
            value=1.0,
            step=0.1,
            help="Initial exponential backoff delay in seconds (default: 1.0)",
        )

    return RuntimeConfig(
        max_concurrency=int(max_concurrency),
        max_retries=int(max_retries),
        retry_base_delay=float(retry_base_delay),
    )


def render_json_export_button(
    result: ValidationResult | BatchValidationResult,
    file_name: str,
) -> None:
    """Render a one-click download button for canonical structured JSON export."""
    if isinstance(result, BatchValidationResult):
        json_payload = format_batch_result_json(result)
        label = "⬇️ Export Batch JSON Report"
    else:
        json_payload = format_validation_result_json(result)
        label = "⬇️ Export Structured JSON"

    st.download_button(
        label=label,
        data=json_payload,
        file_name=file_name,
        mime="application/json",
    )


def render_batch_summary_banner(batch_result: BatchValidationResult) -> None:
    """Render high-level portfolio-wide aggregate summary banner and metric cards for a batch."""
    import streamlit as st

    st.subheader("Batch Audit Summary")

    if batch_result.is_valid:
        st.success(
            f"✅ **Batch Verification Succeeded** — All {batch_result.total_statements} statements "
            "processed successfully with zero mathematical discrepancies."
        )
    elif batch_result.failed_count > 0:
        st.error(
            f"❌ **Batch Issues Flagged** — {batch_result.failed_count} of {batch_result.total_statements} "
            f"statements failed extraction, and {batch_result.total_discrepancies} total discrepancies were detected."
        )
    else:
        st.warning(
            f"⚠️ **Batch Discrepancies Flagged** — {batch_result.total_discrepancies} total discrepancies "
            f"detected across {batch_result.total_statements} statements."
        )

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            label="Total Statements",
            value=str(batch_result.total_statements),
        )

    with col2:
        st.metric(
            label="Success / Failed",
            value=f"{batch_result.successful_count} / {batch_result.failed_count}",
            delta=f"{batch_result.failed_count} Failed" if batch_result.failed_count > 0 else "All Succeeded",
            delta_color="inverse" if batch_result.failed_count > 0 else "normal",
        )

    with col3:
        st.metric(
            label="Cumulative Withdrawals",
            value=f"INR {batch_result.cumulative_withdrawals:,.2f}",
        )

    with col4:
        st.metric(
            label="Cumulative Deposits",
            value=f"INR {batch_result.cumulative_deposits:,.2f}",
        )

    with col5:
        discrepancy_count = batch_result.total_discrepancies
        if discrepancy_count == 0:
            st.metric(
                label="Total Discrepancies",
                value="0",
                delta="Integrity Confirmed",
            )
        else:
            st.metric(
                label="Total Discrepancies",
                value=str(discrepancy_count),
                delta=f"{discrepancy_count} Discrepanc{'ies' if discrepancy_count != 1 else 'y'}",
                delta_color="inverse",
            )


def get_statement_tab_label(stmt: StatementResult) -> str:
    """Return a descriptive tab label combining filename and validation status badge."""
    filename = stmt.pdf_path.name
    if stmt.status == "failed":
        return f"❌ {filename} (Failed)"
    if stmt.result is not None and stmt.result.discrepancies:
        return f"⚠️ {filename} (Discrepancy)"
    return f"✅ {filename} (Valid)"


def render_statement_view(result: ValidationResult, filename: str) -> None:
    """Render full audit view for a single validated statement including metrics, alerts, and ledger."""
    import streamlit as st

    from bank_statement.ui.components import (
        render_discrepancy_diagnostics,
        render_summary_metrics,
        render_transaction_table,
    )

    st.subheader(f"Statement Audit Summary: {filename}")
    render_summary_metrics(result)
    render_discrepancy_diagnostics(result)
    st.subheader("Transaction Ledger")
    render_transaction_table(result.transactions)


def render_batch_tabs(batch_result: BatchValidationResult) -> None:
    """Render dedicated isolated tabs for each statement in a batch."""
    import streamlit as st

    from bank_statement.ui.components import (
        get_statement_tab_label,
        render_statement_view,
    )

    if not batch_result.statements:
        st.info("No statements to display in this batch.")
        return

    tab_labels = [get_statement_tab_label(s) for s in batch_result.statements]
    tabs = st.tabs(tab_labels)

    for tab, stmt in zip(tabs, batch_result.statements):
        with tab:
            filename = stmt.pdf_path.name
            if stmt.status == "failed":
                st.subheader(f"Statement: {filename}")
                st.error(
                    f"❌ **Extraction Failed**: {stmt.error or 'An unknown error occurred during statement processing.'}"
                )
                st.info(
                    "ℹ️ **Diagnostics**: Extraction failed for this statement. "
                    "Other statements in this batch remain unaffected and fully verified."
                )
            else:
                val_result = stmt.result
                assert val_result is not None
                render_statement_view(val_result, filename)


def render_summary_metrics(result: ValidationResult) -> None:
    """Render high-level financial and balance validity summary metric cards."""
    import streamlit as st

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Withdrawals",
            value=f"INR {result.total_withdrawals:,.2f}",
        )

    with col2:
        st.metric(
            label="Total Deposits",
            value=f"INR {result.total_deposits:,.2f}",
        )

    with col3:
        st.metric(
            label="Transactions Parsed",
            value=str(len(result.transactions)),
        )

    with col4:
        if not result.discrepancies:
            st.metric(
                label="Mathematical Validity",
                value="Valid",
                delta="Integrity Confirmed",
            )
        else:
            discrepancy_count = len(result.discrepancies)
            st.metric(
                label="Mathematical Validity",
                value="Discrepancies Flagged",
                delta=f"{discrepancy_count} Discrepanc{'ies' if discrepancy_count != 1 else 'y'}",
                delta_color="inverse",
            )


def render_discrepancy_diagnostics(result: ValidationResult) -> None:
    """Render discrepancy alert cards or a clean confirmation badge.

    When discrepancies exist, renders a prominent alert card above the ledger
    detailing each mismatch (date, expected balance, stated balance, delta) and
    explains that sequential balance checking re-anchored to the stated balance
    to prevent cascading false discrepancies.

    When zero discrepancies exist, renders a success confirmation badge
    indicating full mathematical integrity has been verified.
    """
    import streamlit as st

    if not result.discrepancies:
        st.success(
            "✅ **Mathematical Integrity Verified** — All sequential balance checks "
            "passed. No discrepancies detected across the full transaction ledger."
        )
        return

    discrepancy_count = len(result.discrepancies)
    header = (
        f"⚠️ **Discrepancy Alert** — {discrepancy_count} mathematical "
        f"discrepanc{'ies' if discrepancy_count != 1 else 'y'} detected"
    )

    details_lines: list[str] = []
    for tx in result.discrepancies:
        discrepancy = tx.discrepancy
        assert discrepancy is not None  # guaranteed by ValidationResult contract
        details_lines.append(
            f"- Date: **{tx.date}** | "
            f"Expected Balance: **INR {discrepancy.expected_balance:,.2f}** | "
            f"Stated Running Balance: **INR {discrepancy.stated_balance:,.2f}** | "
            f"Variance Delta: **INR {discrepancy.delta:,.2f}**"
        )

    reanchoring_note = (
        "\n\n> Sequential balance verification re-anchored to the stated running "
        "balance at each discrepancy point. This prevents a single mismatch from "
        "producing cascading false discrepancies in subsequent transactions."
    )

    st.warning(header + "\n\n" + "\n".join(details_lines) + reanchoring_note)


def build_styled_transaction_table(
    transactions: Sequence[Transaction],
) -> pd.io.formats.style.Styler:
    """Build a Pandas DataFrame and apply row-level visual highlight styling for discrepancies."""
    tx_rows: list[dict[str, Any]] = [
        {
            "Date": tx.date,
            "Narration": tx.narration,
            "Cheque / Ref No": tx.chq_ref_no if tx.chq_ref_no else "-",
            "Withdrawal (INR)": f"{tx.withdrawal:,.2f}",
            "Deposit (INR)": f"{tx.deposit:,.2f}",
            "Running Balance (INR)": f"{tx.running_balance:,.2f}",
        }
        for tx in transactions
    ]

    df = pd.DataFrame(tx_rows)

    def _style_discrepancy_rows(data: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=data.index, columns=data.columns)
        for idx, tx in enumerate(transactions):
            if tx.discrepancy is not None:
                styles.iloc[idx] = HIGHLIGHT_ROW_STYLE
        return styles

    return df.style.apply(_style_discrepancy_rows, axis=None)


def render_transaction_table(transactions: Sequence[Transaction]) -> None:
    """Render chronological transactions with distinct visual row styling for discrepancies.

    Transactions with discrepancies are styled with distinct highlight styling
    so anomalies immediately stand out during visual inspection.
    """
    import streamlit as st

    from bank_statement.ui.components import build_styled_transaction_table

    if not transactions:
        st.info("No transactions found in this statement.")
        return

    styled_df = build_styled_transaction_table(transactions)
    st.dataframe(styled_df, use_container_width=True, hide_index=True)




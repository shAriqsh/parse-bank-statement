from typing import Any, Sequence
import pandas as pd  # type: ignore[import-untyped]
import streamlit as st
from bank_statement.models import Transaction, ValidationResult

HIGHLIGHT_ROW_STYLE = "background-color: #fee2e2; color: #991b1b; font-weight: bold"


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




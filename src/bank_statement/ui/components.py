from typing import Any, Sequence
import streamlit as st
from bank_statement.models import Transaction, ValidationResult



def render_summary_metrics(result: ValidationResult) -> None:
    """Render high-level financial and balance validity summary metric cards."""
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
        if result.is_valid:
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


def render_transaction_table(transactions: Sequence[Transaction]) -> None:
    """Render chronological transactions in a clean, scrollable tabular view."""
    if not transactions:
        st.info("No transactions found in this statement.")
        return

    records: list[dict[str, Any]] = [
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

    st.dataframe(records, use_container_width=True, hide_index=True)


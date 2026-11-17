import asyncio
from collections.abc import Coroutine
from pathlib import Path
import shutil
import tempfile
from typing import Any, TypeVar
import streamlit as st
from bank_statement.config import get_gemini_client
from bank_statement.orchestrator import parse_statement
from bank_statement.ui.components import render_summary_metrics, render_transaction_table

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously inside Streamlit's execution thread."""
    try:
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)



def main() -> None:
    st.set_page_config(
        page_title="Bank Statement Audit Inspector",
        page_icon="🏦",
        layout="wide",
    )

    st.title("🏦 Bank Statement Audit Inspector")
    st.caption("Multimodal verification and mathematical balance audit inspector")

    uploaded_file = st.file_uploader(
        "Upload Bank Statement PDF",
        type=["pdf"],
        accept_multiple_files=False,
        help="Drag and drop a bank statement PDF for automated multimodal audit inspection",
    )

    if uploaded_file is None:
        st.info("Please drag and drop a bank statement PDF to begin audit inspection.")
        return

    file_signature = f"{uploaded_file.name}_{uploaded_file.size}"
    cached_signature = st.session_state.get("cached_file_signature")

    if cached_signature != file_signature or "statement_result" not in st.session_state:
        temp_dir = tempfile.mkdtemp()
        temp_pdf_path = Path(temp_dir) / uploaded_file.name
        try:
            temp_pdf_path.write_bytes(uploaded_file.getvalue())

            progress_bar = st.progress(0.0, text="Initializing multimodal extraction...")

            def progress_callback(phase: str, pct: float | None = None) -> None:
                p = pct if pct is not None else 0.0
                clamped_p = min(max(p, 0.0), 1.0)
                progress_bar.progress(clamped_p, text=phase)

            client = None
            try:
                client = get_gemini_client()
            except Exception:
                pass

            result = run_async(
                parse_statement(
                    temp_pdf_path,
                    client=client,
                    progress_callback=progress_callback,
                )
            )

            st.session_state["cached_file_signature"] = file_signature
            st.session_state["statement_result"] = result
            st.session_state["statement_filename"] = uploaded_file.name
            progress_bar.empty()
        finally:
            if temp_pdf_path.exists():
                temp_pdf_path.unlink()
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    result = st.session_state["statement_result"]
    filename = st.session_state.get("statement_filename", uploaded_file.name)

    st.subheader(f"Statement Audit Summary: {filename}")
    render_summary_metrics(result)

    st.subheader("Transaction Ledger")
    render_transaction_table(result.transactions)


main()

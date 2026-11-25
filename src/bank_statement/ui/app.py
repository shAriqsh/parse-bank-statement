import asyncio
from collections.abc import Coroutine
from pathlib import Path
import shutil
import tempfile
from typing import Any, TypeVar
import streamlit as st
from bank_statement.config import get_gemini_client
from bank_statement.orchestrator import parse_batch_statements, parse_statement
from bank_statement.ui.components import (
    render_batch_summary_banner,
    render_batch_tabs,
    render_json_export_button,
    render_sidebar_config,
    render_statement_view,
)

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

    client = None
    try:
        client = get_gemini_client()
    except Exception:
        pass

    runtime_config = render_sidebar_config(api_key_ready=client is not None)

    uploaded_files = st.file_uploader(
        "Upload Bank Statement PDF(s)",
        type=["pdf"],
        accept_multiple_files=True,
        help="Drag and drop bank statement PDFs for automated multimodal audit inspection",
    )

    if not uploaded_files:
        st.info("Please drag and drop bank statement PDFs to begin audit inspection.")
        return

    files_signature = ";".join(sorted(f"{f.name}_{f.size}" for f in uploaded_files))
    cached_signature = st.session_state.get("cached_files_signature") or st.session_state.get("cached_file_signature")

    if len(uploaded_files) == 1:
        uploaded_file = uploaded_files[0]
        if cached_signature != files_signature or "statement_result" not in st.session_state:
            temp_dir = tempfile.mkdtemp()
            temp_pdf_path = Path(temp_dir) / uploaded_file.name
            try:
                temp_pdf_path.write_bytes(uploaded_file.getvalue())

                progress_bar = st.progress(0.0, text="Initializing multimodal extraction...")

                def progress_callback(phase: str, pct: float | None = None) -> None:
                    p = pct if pct is not None else 0.0
                    clamped_p = min(max(p, 0.0), 1.0)
                    progress_bar.progress(clamped_p, text=phase)

                result = run_async(
                    parse_statement(
                        temp_pdf_path,
                        client=client,
                        max_concurrency=runtime_config.max_concurrency,
                        max_retries=runtime_config.max_retries,
                        retry_base_delay=runtime_config.retry_base_delay,
                        progress_callback=progress_callback,
                    )
                )

                st.session_state["cached_files_signature"] = files_signature
                st.session_state["cached_file_signature"] = files_signature
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

        render_statement_view(result, filename)
        render_json_export_button(result, file_name=f"{Path(filename).stem}_transactions.json")

    else:
        # Multi-statement batch processing flow
        if cached_signature != files_signature or "batch_result" not in st.session_state:
            temp_dir = tempfile.mkdtemp()
            temp_paths: list[Path] = []
            try:
                for uf in uploaded_files:
                    p = Path(temp_dir) / uf.name
                    p.write_bytes(uf.getvalue())
                    temp_paths.append(p)

                progress_bar = st.progress(0.0, text="Initializing batch extraction...")

                def batch_progress_callback(phase: str, pct: float | None = None) -> None:
                    p = pct if pct is not None else 0.0
                    clamped_p = min(max(p, 0.0), 1.0)
                    progress_bar.progress(clamped_p, text=phase)

                batch_result = run_async(
                    parse_batch_statements(
                        temp_paths,
                        client=client,
                        max_concurrency=runtime_config.max_concurrency,
                        max_retries=runtime_config.max_retries,
                        retry_base_delay=runtime_config.retry_base_delay,
                        progress_callback=batch_progress_callback,
                    )
                )

                st.session_state["cached_files_signature"] = files_signature
                st.session_state["cached_file_signature"] = files_signature
                st.session_state["batch_result"] = batch_result
                progress_bar.empty()
            finally:
                for p in temp_paths:
                    if p.exists():
                        p.unlink()
                if Path(temp_dir).exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)

        batch_result = st.session_state["batch_result"]
        render_batch_summary_banner(batch_result)
        render_json_export_button(batch_result, file_name="batch_audit_report.json")
        render_batch_tabs(batch_result)


main()

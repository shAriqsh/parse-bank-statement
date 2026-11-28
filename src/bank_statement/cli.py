import argparse
import asyncio
import sys
from pathlib import Path
from typing import Sequence

from bank_statement.config import get_gemini_client
from bank_statement.orchestrator import parse_batch_statements, parse_statement
from bank_statement.reporter import (
    export_batch_json,
    export_transactions_json,
    format_batch_cli_summary,
    format_cli_summary,
)
from bank_statement.ui.runner import launch_ui


def resolve_pdf_paths(inputs: Sequence[str | Path]) -> list[Path]:
    """Resolve and validate a sequence of file paths and directories to PDF files.

    - Existing files are validated and appended.
    - Existing directories are scanned non-recursively for '*.pdf' files (case-insensitive)
    - and sorted alphabetically.
    - If a path does not exist, raises FileNotFoundError.
    - If a directory contains zero PDF files, raises ValueError.
    """
    resolved_paths: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_file():
            resolved_paths.append(path)
        elif path.is_dir():
            pdf_files = sorted(
                [p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
                key=lambda p: p.name.lower(),
            )
            if not pdf_files:
                raise ValueError(f"Directory '{path}' contains zero PDF files")
            resolved_paths.extend(pdf_files)
        else:
            raise FileNotFoundError(f"Bank statement file not found at '{path}'")
    return resolved_paths


def build_ui_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for the 'ui' subcommand."""
    parser = argparse.ArgumentParser(
        description="Launch Streamlit Bank Statement Audit Inspector"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port to run the Streamlit UI on (default: 8501)",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host address to bind the Streamlit UI to (default: localhost)",
    )
    return parser


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Multimodal Bank Statement Parser & Mathematical Balance Validator",
        epilog="Subcommands:\n  ui    Launch the Streamlit web audit inspector (see 'ui --help')",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "pdf_paths",
        nargs="*",
        default=["account.pdf"],
        help="Path(s) to bank statement PDF file(s) or directory containing PDFs (default: account.pdf)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="transactions.json",
        help="Path to export the structured JSON artifact (default: transactions.json)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory to export individual per-statement JSON files (<statement_stem>_transactions.json)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=5,
        help="Maximum concurrent extraction workers (default: 5)",
    )
    return parser



async def run_pipeline(
    pdf_paths: Sequence[str | Path] | str | Path,
    output_path: str | Path = "transactions.json",
    concurrency: int = 5,
    output_dir: str | Path | None = None,
) -> int:
    """Execute the asynchronous multimodal parsing, validation, export, and reporting pipeline."""
    inputs: Sequence[str | Path]
    if isinstance(pdf_paths, (str, Path)):
        inputs = [pdf_paths]
    else:
        inputs = pdf_paths

    try:
        resolved = resolve_pdf_paths(inputs)
    except (FileNotFoundError, ValueError) as err:
        print(f"Error: {err}")
        return 1

    client = get_gemini_client()

    if len(resolved) == 1:
        result = await parse_statement(resolved[0], client=client, max_concurrency=concurrency)
        export_transactions_json(result, output_path)
        if output_dir is not None:
            dir_target = Path(output_dir)
            dir_target.mkdir(parents=True, exist_ok=True)
            export_transactions_json(result, dir_target / f"{resolved[0].stem}_transactions.json")
        summary_output = format_cli_summary(result)
        print(summary_output)
        return 0

    batch_result = await parse_batch_statements(resolved, client=client, max_concurrency=concurrency)
    export_batch_json(batch_result, output_path=output_path, output_dir=output_dir)
    summary_output = format_batch_cli_summary(batch_result)
    print(summary_output)
    return 0 if batch_result.is_valid else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if args_list and args_list[0] == "ui":
        ui_parser = build_ui_parser()
        ui_args = ui_parser.parse_args(args_list[1:])
        return launch_ui(port=ui_args.port, host=ui_args.host)

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    pdf_inputs = args.pdf_paths if args.pdf_paths else ["account.pdf"]

    return asyncio.run(
        run_pipeline(
            pdf_paths=pdf_inputs,
            output_path=args.output,
            concurrency=args.concurrency,
            output_dir=args.output_dir,
        )
    )


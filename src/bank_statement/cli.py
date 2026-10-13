import argparse
import asyncio
from pathlib import Path
from typing import Sequence
from bank_statement.config import get_gemini_client
from bank_statement.orchestrator import parse_statement
from bank_statement.reporter import export_transactions_json, format_cli_summary


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Multimodal Bank Statement Parser & Mathematical Balance Validator"
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="account.pdf",
        help="Path to the bank statement PDF file (default: account.pdf)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="transactions.json",
        help="Path to export the structured JSON artifact (default: transactions.json)",
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
    pdf_path: str | Path,
    output_path: str | Path = "transactions.json",
    concurrency: int = 5,
) -> int:
    """Execute the asynchronous multimodal parsing, validation, export, and reporting pipeline."""
    path = Path(pdf_path)
    if not path.is_file():
        print(f"Error: Bank statement file not found at '{path}'")
        return 1

    client = get_gemini_client()
    result = await parse_statement(path, client=client, max_concurrency=concurrency)

    export_transactions_json(result, output_path)

    summary_output = format_cli_summary(result)
    print(summary_output)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    return asyncio.run(
        run_pipeline(
            pdf_path=args.pdf_path,
            output_path=args.output,
            concurrency=args.concurrency,
        )
    )

import json
from pathlib import Path
from typing import Any

from bank_statement.models import (
    BatchValidationResult,
    Transaction,
    ValidationResult,
)


def _transaction_to_dict(tx: Transaction) -> dict[str, Any]:
    """Serialize a Transaction domain model into JSON-compatible dictionary."""
    discrepancy_dict: dict[str, str] | None = None
    if tx.discrepancy is not None:
        discrepancy_dict = {
            "expected_balance": f"{tx.discrepancy.expected_balance:.2f}",
            "stated_balance": f"{tx.discrepancy.stated_balance:.2f}",
            "delta": f"{tx.discrepancy.delta:.2f}",
        }

    return {
        "date": tx.date,
        "narration": tx.narration,
        "chq_ref_no": tx.chq_ref_no,
        "withdrawal": f"{tx.withdrawal:.2f}",
        "deposit": f"{tx.deposit:.2f}",
        "running_balance": f"{tx.running_balance:.2f}",
        "discrepancy": discrepancy_dict,
    }


def _validation_result_to_dict(result: ValidationResult) -> dict[str, Any]:
    """Serialize a ValidationResult into JSON-compatible summary, transactions, and discrepancies."""
    return {
        "summary": {
            "total_withdrawals": f"{result.total_withdrawals:.2f}",
            "total_deposits": f"{result.total_deposits:.2f}",
            "transaction_count": len(result.transactions),
            "discrepancy_count": len(result.discrepancies),
            "is_valid": result.is_valid,
        },
        "transactions": [_transaction_to_dict(tx) for tx in result.transactions],
        "discrepancies": [_transaction_to_dict(tx) for tx in result.discrepancies],
    }


def format_validation_result_json(result: ValidationResult) -> str:
    """Serialize a ValidationResult to a formatted canonical JSON string."""
    payload = _validation_result_to_dict(result)
    return json.dumps(payload, indent=2)


def export_transactions_json(
    result: ValidationResult,
    output_path: str | Path,
) -> None:
    """Export validated transactions, statement totals, and discrepancies to a JSON file.

    Args:
        result: ValidationResult instance produced by the statement validator.
        output_path: Target path for the output JSON artifact.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_validation_result_json(result), encoding="utf-8")


def _batch_validation_result_to_dict(batch_result: BatchValidationResult) -> dict[str, Any]:
    """Serialize a BatchValidationResult into a JSON-compatible dictionary."""
    statements_list: list[dict[str, Any]] = []
    for stmt in batch_result.statements:
        if stmt.status == "success" and stmt.result is not None:
            stmt_dict: dict[str, Any] = {
                "pdf_path": str(stmt.pdf_path),
                "status": stmt.status,
                **_validation_result_to_dict(stmt.result),
                "error": None,
            }
        else:
            stmt_dict = {
                "pdf_path": str(stmt.pdf_path),
                "status": stmt.status,
                "summary": None,
                "transactions": [],
                "discrepancies": [],
                "error": stmt.error,
            }
        statements_list.append(stmt_dict)

    return {
        "batch_summary": {
            "total_statements": batch_result.total_statements,
            "successful_count": batch_result.successful_count,
            "failed_count": batch_result.failed_count,
            "cumulative_withdrawals": f"{batch_result.cumulative_withdrawals:.2f}",
            "cumulative_deposits": f"{batch_result.cumulative_deposits:.2f}",
            "total_discrepancies": batch_result.total_discrepancies,
            "is_valid": batch_result.is_valid,
        },
        "statements": statements_list,
    }


def format_batch_result_json(batch_result: BatchValidationResult) -> str:
    """Serialize a BatchValidationResult to a formatted canonical JSON string."""
    payload = _batch_validation_result_to_dict(batch_result)
    return json.dumps(payload, indent=2)


def export_batch_json(
    batch_result: BatchValidationResult,
    output_path: str | Path,
    output_dir: str | Path | None = None,
) -> None:
    """Export consolidated batch validation results and optional per-statement JSON files.

    Args:
        batch_result: BatchValidationResult instance produced by the batch orchestrator.
        output_path: Target path for the consolidated batch JSON report.
        output_dir: Optional directory to write individual <statement_stem>_transactions.json files.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(format_batch_result_json(batch_result), encoding="utf-8")

    if output_dir is not None:
        dir_target = Path(output_dir)
        dir_target.mkdir(parents=True, exist_ok=True)
        for stmt in batch_result.statements:
            if stmt.status == "success" and stmt.result is not None:
                individual_target = dir_target / f"{stmt.pdf_path.stem}_transactions.json"
                export_transactions_json(stmt.result, individual_target)


def format_cli_summary(result: ValidationResult) -> str:
    """Generate a formatted human-readable CLI summary and diagnostic report.

    Args:
        result: ValidationResult instance produced by the statement validator.

    Returns:
        Formatted summary string with totals, verified count, and optional discrepancy table.
    """
    discrepancy_count = len(result.discrepancies)
    status_text = "VERIFIED (All balances matched)" if result.is_valid else "DISCREPANCIES DETECTED"

    lines = [
        "=" * 60,
        "                BANK STATEMENT SUMMARY",
        "=" * 60,
        f"Total Withdrawals: INR {result.total_withdrawals:,.2f}",
        f"Total Deposits:    INR {result.total_deposits:,.2f}",
        f"Transactions Parsed: {len(result.transactions)}",
        f"Flagged Discrepancies: {discrepancy_count}",
        f"Validation Status: {status_text}",
        "=" * 60,
    ]

    if discrepancy_count > 0:
        lines.append("")
        lines.append("DISCREPANCY DIAGNOSTICS")
        lines.append("-" * 95)
        lines.append(
            f"{'Date':<12} | {'Narration':<35} | {'Stated Bal':<12} | {'Expected Bal':<12} | {'Delta':<10}"
        )
        lines.append("-" * 95)

        for tx in result.discrepancies:
            if tx.discrepancy is None:
                continue
            date_str = tx.date
            # Truncate long narrations for display
            narration_str = (tx.narration[:32] + "...") if len(tx.narration) > 35 else tx.narration
            stated_bal = f"{tx.discrepancy.stated_balance:.2f}"
            expected_bal = f"{tx.discrepancy.expected_balance:.2f}"
            delta_val = tx.discrepancy.delta
            delta_str = f"+{delta_val:.2f}" if delta_val > 0 else f"{delta_val:.2f}"

            lines.append(
                f"{date_str:<12} | {narration_str:<35} | {stated_bal:>12} | {expected_bal:>12} | {delta_str:>10}"
            )

        lines.append("-" * 95)

    return "\n".join(lines)


def format_batch_cli_summary(batch_result: BatchValidationResult) -> str:
    """Generate a formatted human-readable CLI summary and diagnostic report for batch processing.

    Args:
        batch_result: BatchValidationResult instance produced by the batch orchestrator.

    Returns:
        Formatted summary string with batch overview, per-statement table, and targeted diagnostics.
    """
    status_text = (
        "VERIFIED (All statements passed with zero discrepancies)"
        if batch_result.is_valid
        else "FAILED / DISCREPANCIES DETECTED"
    )

    lines = [
        "=" * 85,
        "                         BATCH STATEMENT SUMMARY",
        "=" * 85,
        f"Total Statements:        {batch_result.total_statements} (Passed: {batch_result.successful_count}, Failed: {batch_result.failed_count})",
        f"Cumulative Withdrawals:  INR {batch_result.cumulative_withdrawals:,.2f}",
        f"Cumulative Deposits:     INR {batch_result.cumulative_deposits:,.2f}",
        f"Total Discrepancies:     {batch_result.total_discrepancies}",
        f"Validation Status:       {status_text}",
        "=" * 85,
        "",
        f"{'File':<25} | {'Txs':<5} | {'Status':<14} | {'Discrepancies':<13} | {'Withdrawals (INR)':>17} | {'Deposits (INR)':>16}",
        "-" * 105,
    ]

    for stmt in batch_result.statements:
        filename = stmt.pdf_path.name
        if len(filename) > 25:
            filename = filename[:22] + "..."
        if stmt.status == "success" and stmt.result is not None:
            tx_count = str(len(stmt.result.transactions))
            discrepancy_count = str(len(stmt.result.discrepancies))
            stmt_status = "VERIFIED" if stmt.result.is_valid else "DISCREPANCIES"
            withdrawals = f"{stmt.result.total_withdrawals:,.2f}"
            deposits = f"{stmt.result.total_deposits:,.2f}"
        else:
            tx_count = "-"
            discrepancy_count = "-"
            stmt_status = "FAILED"
            withdrawals = "-"
            deposits = "-"

        lines.append(
            f"{filename:<25} | {tx_count:<5} | {stmt_status:<14} | {discrepancy_count:<13} | {withdrawals:>17} | {deposits:>16}"
        )

    lines.append("-" * 105)

    # Render targeted discrepancy diagnostics for statements with mismatches
    for stmt in batch_result.statements:
        if stmt.status == "success" and stmt.result is not None and stmt.result.discrepancies:
            lines.append("")
            lines.append(f"DISCREPANCY DIAGNOSTICS: {stmt.pdf_path.name}")
            lines.append("-" * 95)
            lines.append(
                f"{'Date':<12} | {'Narration':<35} | {'Stated Bal':<12} | {'Expected Bal':<12} | {'Delta':<10}"
            )
            lines.append("-" * 95)

            for tx in stmt.result.discrepancies:
                if tx.discrepancy is None:
                    continue
                date_str = tx.date
                narration_str = (tx.narration[:32] + "...") if len(tx.narration) > 35 else tx.narration
                stated_bal = f"{tx.discrepancy.stated_balance:.2f}"
                expected_bal = f"{tx.discrepancy.expected_balance:.2f}"
                delta_val = tx.discrepancy.delta
                delta_str = f"+{delta_val:.2f}" if delta_val > 0 else f"{delta_val:.2f}"

                lines.append(
                    f"{date_str:<12} | {narration_str:<35} | {stated_bal:>12} | {expected_bal:>12} | {delta_str:>10}"
                )

            lines.append("-" * 95)

    # Render failed statements callouts if any occurred
    failed_statements = [s for s in batch_result.statements if s.status == "failed"]
    if failed_statements:
        lines.append("")
        lines.append("FAILED STATEMENTS:")
        lines.append("-" * 95)
        for s in failed_statements:
            lines.append(f"• {s.pdf_path.name}: {s.error or 'Unknown error'}")
        lines.append("-" * 95)

    return "\n".join(lines)


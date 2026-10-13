import json
from pathlib import Path
from typing import Any
from bank_statement.models import Transaction, ValidationResult


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

    payload = {
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

    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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

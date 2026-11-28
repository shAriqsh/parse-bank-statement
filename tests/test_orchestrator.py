from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from bank_statement.extractor import ExtractedPage, ExtractedTransaction
from bank_statement.models import BatchValidationResult, Transaction, ValidationResult
from bank_statement.orchestrator import parse_batch_statements, parse_statement


@pytest.mark.anyio
async def test_parse_statement_with_injected_extraction_adapter() -> None:
    async def fake_extractor(path: str | Path, **kwargs: object) -> list[Transaction]:
        return [
            Transaction(
                date="01-01-2024",
                narration="INJECTED OPENING BALANCE",
                withdrawal=Decimal("0.00"),
                deposit=Decimal("1000.00"),
                running_balance=Decimal("1000.00"),
            ),
            Transaction(
                date="02-01-2024",
                narration="INJECTED PAYMENT",
                withdrawal=Decimal("200.00"),
                deposit=Decimal("0.00"),
                running_balance=Decimal("800.00"),
            ),
        ]

    result = await parse_statement("dummy.pdf", extractor=fake_extractor)

    assert isinstance(result, ValidationResult)
    assert result.is_valid is True
    assert len(result.transactions) == 2
    assert result.total_deposits == Decimal("1000.00")
    assert result.total_withdrawals == Decimal("200.00")
    assert len(result.discrepancies) == 0


@pytest.mark.anyio
async def test_parse_statement_identifies_and_flags_discrepancies() -> None:
    async def fake_extractor_with_discrepancy(path: str | Path, **kwargs: object) -> list[Transaction]:
        return [
            Transaction(
                date="01-01-2024",
                narration="OPENING BALANCE",
                withdrawal=Decimal("0.00"),
                deposit=Decimal("1000.00"),
                running_balance=Decimal("1000.00"),
            ),
            Transaction(
                date="02-01-2024",
                narration="MISCALCULATED TRANSACTION",
                withdrawal=Decimal("200.00"),
                deposit=Decimal("0.00"),
                running_balance=Decimal("700.00"),  # Expected: 800.00, stated: 700.00 -> delta: -100.00
            ),
        ]

    result = await parse_statement("dummy.pdf", extractor=fake_extractor_with_discrepancy)

    assert isinstance(result, ValidationResult)
    assert result.is_valid is False
    assert len(result.discrepancies) == 1
    disc = result.discrepancies[0].discrepancy
    assert disc is not None
    assert disc.expected_balance == Decimal("800.00")
    assert disc.stated_balance == Decimal("700.00")
    assert disc.delta == Decimal("-100.00")


@pytest.mark.anyio
async def test_parse_statement_forwards_configuration_to_extractor() -> None:
    captured_kwargs: dict[str, Any] = {}
    mock_client = MagicMock()

    async def capturing_extractor(path: str | Path, **kwargs: Any) -> list[Transaction]:
        captured_kwargs.update(kwargs)
        return []

    result = await parse_statement(
        "dummy.pdf",
        client=mock_client,
        max_concurrency=7,
        max_retries=4,
        retry_base_delay=0.5,
        extractor=capturing_extractor,
    )

    assert result.is_valid is True
    assert captured_kwargs["client"] is mock_client
    assert captured_kwargs["max_concurrency"] == 7
    assert captured_kwargs["max_retries"] == 4
    assert captured_kwargs["retry_base_delay"] == 0.5


@pytest.mark.anyio
async def test_parse_statement_propagates_extractor_exception() -> None:
    async def failing_extractor(path: str | Path, **kwargs: object) -> list[Transaction]:
        raise RuntimeError("Unrecoverable downstream extraction failure")

    with pytest.raises(RuntimeError, match="Unrecoverable downstream extraction failure"):
        await parse_statement("dummy.pdf", extractor=failing_extractor)


@pytest.mark.anyio
async def test_parse_statement_full_pdf_integration_with_real_pdf() -> None:
    # Uses actual account.pdf (31 pages) end-to-end through the default extraction adapter seam
    pdf_path = Path("account.pdf")

    from bank_statement.extractor import _rasterize_pdf_pages

    buffers = _rasterize_pdf_pages(pdf_path, resolution=36)
    buffer_to_idx = {buf: i for i, buf in enumerate(buffers)}

    def mock_generate_content(*args: object, contents: list[Any], **kwargs: object) -> MagicMock:
        image_bytes = getattr(getattr(contents[0], "inline_data", None), "data", b"")
        page_idx = buffer_to_idx[image_bytes]
        if page_idx == 0:
            tx = ExtractedTransaction(
                date="01-01-2024",
                narration="OPENING BALANCE",
                withdrawal="0.00",
                deposit="10000.00",
                balance="10000.00",
            )
        else:
            current_balance = Decimal("10000.00") - (Decimal("100.00") * page_idx)
            tx = ExtractedTransaction(
                date=f"{page_idx + 1:02d}-01-2024",
                narration=f"PAGE {page_idx} WITHDRAWAL",
                withdrawal="100.00",
                deposit="0.00",
                balance=str(current_balance),
            )
        return MagicMock(parsed=ExtractedPage(transactions=[tx]))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    result = await parse_statement(
        pdf_path=pdf_path,
        client=mock_client,
        max_concurrency=5,
        resolution=36,
    )

    assert result.is_valid is True
    assert len(result.transactions) == 31
    assert result.total_withdrawals == Decimal("3000.00")
    assert result.total_deposits == Decimal("10000.00")
    assert result.transactions[-1].running_balance == Decimal("7000.00")
    assert len(result.discrepancies) == 0


@pytest.mark.anyio
async def test_parse_batch_statements_aggregates_multiple_statements_with_isolated_baselines() -> None:
    async def multi_statement_extractor(path: str | Path, **kwargs: object) -> list[Transaction]:
        str_path = str(path)
        if "statement_1.pdf" in str_path:
            return [
                Transaction(
                    date="01-01-2024",
                    narration="ACCT 1 OPENING",
                    withdrawal=Decimal("0.00"),
                    deposit=Decimal("5000.00"),
                    running_balance=Decimal("5000.00"),
                ),
                Transaction(
                    date="02-01-2024",
                    narration="ACCT 1 WITHDRAWAL",
                    withdrawal=Decimal("1000.00"),
                    deposit=Decimal("0.00"),
                    running_balance=Decimal("4000.00"),
                ),
            ]
        elif "statement_2.pdf" in str_path:
            return [
                Transaction(
                    date="01-02-2024",
                    narration="ACCT 2 OPENING",
                    withdrawal=Decimal("0.00"),
                    deposit=Decimal("100000.00"),
                    running_balance=Decimal("100000.00"),
                ),
                Transaction(
                    date="05-02-2024",
                    narration="ACCT 2 DEPOSIT",
                    withdrawal=Decimal("0.00"),
                    deposit=Decimal("20000.00"),
                    running_balance=Decimal("120000.00"),
                ),
            ]
        return []

    batch_result = await parse_batch_statements(
        ["statement_1.pdf", Path("statement_2.pdf")],
        extractor=multi_statement_extractor,
    )

    assert isinstance(batch_result, BatchValidationResult)
    assert batch_result.total_statements == 2
    assert batch_result.successful_count == 2
    assert batch_result.failed_count == 0
    assert batch_result.is_valid is True
    assert batch_result.total_discrepancies == 0
    assert batch_result.cumulative_withdrawals == Decimal("1000.00")
    assert batch_result.cumulative_deposits == Decimal("125000.00")
    assert len(batch_result.statements) == 2
    assert batch_result.statements[0].status == "success"
    assert batch_result.statements[1].status == "success"


@pytest.mark.anyio
async def test_parse_batch_statements_fault_isolation_on_error() -> None:
    async def faulty_batch_extractor(path: str | Path, **kwargs: object) -> list[Transaction]:
        str_path = str(path)
        if "bad.pdf" in str_path:
            raise ValueError("Corrupt PDF stream")
        elif "with_error.pdf" in str_path:
            return [
                Transaction(
                    date="01-01-2024",
                    narration="OPENING",
                    withdrawal=Decimal("0.00"),
                    deposit=Decimal("100.00"),
                    running_balance=Decimal("100.00"),
                ),
                Transaction(
                    date="02-01-2024",
                    narration="WRONG BALANCE",
                    withdrawal=Decimal("20.00"),
                    deposit=Decimal("0.00"),
                    running_balance=Decimal("50.00"),  # Expected: 80.00 -> discrepancy
                ),
            ]
        return [
            Transaction(
                date="01-01-2024",
                narration="CLEAN",
                withdrawal=Decimal("10.00"),
                deposit=Decimal("0.00"),
                running_balance=Decimal("90.00"),
            )
        ]

    batch_result = await parse_batch_statements(
        ["clean.pdf", "bad.pdf", "with_error.pdf"],
        extractor=faulty_batch_extractor,
    )

    assert batch_result.total_statements == 3
    assert batch_result.successful_count == 2
    assert batch_result.failed_count == 1
    assert batch_result.total_discrepancies == 1
    assert batch_result.is_valid is False
    assert batch_result.statements[0].status == "success"
    assert batch_result.statements[1].status == "failed"
    assert batch_result.statements[1].error == "Corrupt PDF stream"
    assert batch_result.statements[1].result is None
    assert batch_result.statements[2].status == "success"
    assert batch_result.statements[2].result is not None
    assert len(batch_result.statements[2].result.discrepancies) == 1


@pytest.mark.anyio
async def test_parse_batch_statements_empty_input() -> None:
    batch_result = await parse_batch_statements([])

    assert batch_result.total_statements == 0
    assert batch_result.successful_count == 0
    assert batch_result.failed_count == 0
    assert batch_result.cumulative_withdrawals == Decimal("0.00")
    assert batch_result.cumulative_deposits == Decimal("0.00")
    assert batch_result.total_discrepancies == 0
    assert batch_result.is_valid is True
    assert batch_result.statements == []


@pytest.mark.anyio
async def test_parse_batch_statements_forwards_parameters() -> None:
    calls: list[dict[str, Any]] = []
    mock_client = MagicMock()

    async def capturing_extractor(path: str | Path, **kwargs: Any) -> list[Transaction]:
        calls.append({"path": path, **kwargs})
        return [
            Transaction(
                date="01-01-2024",
                narration="OPENING",
                withdrawal=Decimal("0.00"),
                deposit=Decimal("100.00"),
                running_balance=Decimal("100.00"),
            )
        ]

    batch_result = await parse_batch_statements(
        ["s1.pdf", "s2.pdf"],
        client=mock_client,
        max_concurrency=4,
        max_retries=2,
        retry_base_delay=0.25,
        extractor=capturing_extractor,
        custom_flag=True,
    )

    assert batch_result.is_valid is True
    assert len(calls) == 2
    for call in calls:
        assert call["client"] is mock_client
        assert call["max_concurrency"] == 4
        assert call["max_retries"] == 2
        assert call["retry_base_delay"] == 0.25
        assert call["custom_flag"] is True


@pytest.mark.anyio
async def test_parse_statement_forwards_progress_callback() -> None:
    progress_updates: list[tuple[str, float | None]] = []

    def mock_progress(phase: str, pct: float | None = None) -> None:
        progress_updates.append((phase, pct))

    async def fake_extractor(path: str | Path, **kwargs: Any) -> list[Transaction]:
        cb = kwargs.get("progress_callback")
        if cb:
            cb("Processing page 1", 0.5)
            cb("Done", 1.0)
        return [
            Transaction(
                date="01-01-2024",
                narration="TEST",
                withdrawal=Decimal("0.00"),
                deposit=Decimal("100.00"),
                running_balance=Decimal("100.00"),
            )
        ]

    result = await parse_statement("test.pdf", extractor=fake_extractor, progress_callback=mock_progress)
    assert result.is_valid is True
    assert len(progress_updates) == 2
    assert progress_updates[0] == ("Processing page 1", 0.5)
    assert progress_updates[1] == ("Done", 1.0)


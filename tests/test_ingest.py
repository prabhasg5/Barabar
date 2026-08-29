import csv
import io
from datetime import date
from pathlib import Path

import pytest

from ingest.load import IngestError, Ledger, load

ROOT = Path(__file__).resolve().parents[1]

VALID = {
    "orders.csv":
        "order_id,created_at,customer_ref,customer_name,pincode,gross_amount_paise,status\n"
        "order_1,01/01/2026,cust_1,Aarav Sharma,560001,129900,paid\n"
        "order_2,02/01/2026,cust_2,Priya Nair,400002,84900,paid\n",
    "payments.csv":
        "payment_id,order_id,captured_at,amount_paise,method,fee_paise,gst_paise,settlement_id,status\n"
        "pay_1,order_1,2026-01-01 10:15:00,129900,card,2598,468,setl_1,captured\n"
        "pay_2,order_2,2026-01-02 18:40:11,84900,upi,0,0,setl_1,captured\n",
    "refunds.csv":
        "refund_id,payment_id,created_at,amount_paise,type,settlement_id,status\n"
        "rfnd_1,pay_1,2026-01-09,129900,refund,setl_1,processed\n",
    "settlements.csv":
        "settlement_id,settled_at,utr,net_amount_paise,fee_paise,gst_paise,refund_paise,adjustment_paise\n"
        "setl_1,05-Jan-26,207592797549,81834,2598,468,129900,0\n",
    "bank_statement.csv":
        "txn_date,narration,credit_paise,debit_paise,closing_balance_paise,bank_ref\n"
        "05/01/2026,NEFT-RAZORPAY SOFTWARE PRIVA-207592797549-HDFC-XXXXX,81834,0,81834,HDFC1\n",
}


def build(folder: Path, files: dict[str, str] | None = None) -> Path:
    for name, body in (files or VALID).items():
        folder.joinpath(name).write_text(body, encoding="utf-8")
    return folder


def edit(files: dict[str, str], name: str, row: int, column: str,
         value: str) -> dict[str, str]:
    """Return `files` with one cell changed. Row 0 is the first data row.

    Takes the set to edit rather than always starting from VALID, so edits chain.
    """
    rows = list(csv.DictReader(io.StringIO(files[name])))
    rows[row][column] = value
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return {**files, name: out.getvalue()}


def test_valid_set_loads(tmp_path):
    ledger = load(build(tmp_path))
    assert ledger.counts() == {"orders.csv": 2, "payments.csv": 2, "refunds.csv": 1,
                               "settlements.csv": 1, "bank_statement.csv": 1}


def test_dates_normalise_across_formats(tmp_path):
    """Three formats in three files, all landing on the same kind of thing."""
    ledger = load(build(tmp_path))
    assert ledger.orders[0]["created_at"] == date(2026, 1, 1)
    assert ledger.payments[0]["captured_at"] == date(2026, 1, 1)
    assert ledger.settlements[0]["settled_at"] == date(2026, 1, 5)
    assert ledger.bank[0]["txn_date"] == date(2026, 1, 5)


@pytest.mark.parametrize(
    "name, column, value, reason",
    [
        ("payments.csv", "amount_paise", "", "amount_paise is empty"),
        ("payments.csv", "amount_paise", "1299.00", "has a decimal point"),
        ("payments.csv", "amount_paise", "1,299", "is not a whole number"),
        ("payments.csv", "method", "cheque", "is not one of upi, card"),
        ("payments.csv", "payment_id", "", "payment_id is empty"),
        ("orders.csv", "created_at", "31/31/2026", "is not a date I recognise"),
        ("orders.csv", "created_at", "", "created_at is empty"),
        ("refunds.csv", "amount_paise", "-500", "is negative"),
        ("refunds.csv", "type", "reversal", "is not one of refund, chargeback"),
        ("settlements.csv", "settled_at", "last Tuesday", "is not a date I recognise"),
    ],
)
def test_bad_cell_fails_with_row_number_and_reason(tmp_path, name, column, value, reason):
    build(tmp_path, edit(VALID, name, 0, column, value))
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert len(raised.value.problems) == 1
    problem = raised.value.problems[0]
    assert problem.startswith(f"Row 2 in {name}:")
    assert reason in problem
    assert problem.endswith("Fix the row or remove it, then run again.")


def test_row_number_points_at_the_right_line(tmp_path):
    """Second data row is line 3, the number a person sees in their spreadsheet."""
    build(tmp_path, edit(VALID, "payments.csv", 1, "amount_paise", "oops"))
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert raised.value.problems[0].startswith("Row 3 in payments.csv:")


def test_every_problem_is_reported_not_just_the_first(tmp_path):
    files = edit(VALID, "payments.csv", 0, "amount_paise", "")
    files = edit(files, "orders.csv", 1, "created_at", "nope")
    build(tmp_path, files)
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert len(raised.value.problems) == 2
    assert {p.split(" in ")[1].split(":")[0] for p in raised.value.problems} == {
        "payments.csv", "orders.csv"}


def test_duplicate_id_is_rejected(tmp_path):
    build(tmp_path, edit(VALID, "payments.csv", 1, "payment_id", "pay_1"))
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert "repeats an id first used on row 2" in raised.value.problems[0]


def test_missing_column_is_named(tmp_path):
    build(tmp_path, {**VALID, "payments.csv": VALID["payments.csv"].replace(",fee_paise", "", 1)})
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert "payments.csv has no fee_paise column" in raised.value.problems[0]


def test_missing_file_is_named(tmp_path):
    files = dict(VALID)
    del files["refunds.csv"]
    build(tmp_path, files)
    with pytest.raises(IngestError) as raised:
        load(tmp_path)
    assert "refunds.csv is missing" in raised.value.problems[0]


def test_findings_are_not_rejected(tmp_path):
    """The whole point. An orphan payment, an unlinked refund and an unsettled payment
    are E06, E08 and E02 -- they must load, or the tool finds nothing."""
    files = edit(VALID, "payments.csv", 0, "order_id", "")
    files = edit(files, "payments.csv", 0, "settlement_id", "")
    files = edit(files, "refunds.csv", 0, "payment_id", "")
    ledger = load(build(tmp_path, files))
    assert ledger.payments[0]["order_id"] == ""
    assert ledger.payments[0]["settlement_id"] == ""
    assert ledger.refunds[0]["payment_id"] == ""


def test_unreadable_narration_is_not_a_bad_row(tmp_path):
    """E13 is a finding about a string, not a reason to refuse the credit it describes."""
    ledger = load(build(tmp_path, edit(VALID, "bank_statement.csv", 0, "narration",
                                       "*NEFT*//..//")))
    assert ledger.bank[0]["credit_paise"] == 81834


def test_nothing_loads_when_anything_fails(tmp_path):
    build(tmp_path, edit(VALID, "payments.csv", 0, "amount_paise", ""))
    with pytest.raises(IngestError):
        load(tmp_path)


@pytest.mark.parametrize("name", ["train", "heldout"])
def test_generated_datasets_load_with_matching_row_counts(name):
    folder = ROOT.joinpath("data", name)
    if not folder.exists():
        pytest.skip(f"run: PYTHONPATH=src python -m generate {name}")
    ledger = load(folder)
    for filename, count in ledger.counts().items():
        lines = folder.joinpath(filename).read_text(encoding="utf-8").strip().splitlines()
        assert count == len(lines) - 1, filename

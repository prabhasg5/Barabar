import csv
import io
from datetime import date
from pathlib import Path

import pytest

from ingest.load import SCHEMAS, IngestError, Ledger, detect, load

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


# --- detection: files identified by header signature, not by filename -----------------
#
# A merchant's exports are named whatever their aggregator named them. The scruffy folder
# below is what that actually looks like: junk filenames, one header an editor has
# column-aligned, and one unrelated CSV that has no business being ingested.

SCRUFFY = {
    "orders.csv": "orders_export(2).csv",
    "payments.csv": "rzp_pmt_sep.csv",
    "refunds.csv": "refunds.csv",                  # one left conventional on purpose
    "settlements.csv": "settlement-report.csv",
    "bank_statement.csv": "acct_stmt_0904.csv",    # and this one gets a padded header
}


@pytest.fixture
def scruffy(tmp_path):
    """Held-out's five files, renamed the way a real export arrives."""
    source = ROOT.joinpath("data", "heldout")
    if not source.exists():
        pytest.skip("run: PYTHONPATH=src python -m generate heldout")
    for real, junk in SCRUFFY.items():
        body = source.joinpath(real).read_text(encoding="utf-8")
        if junk.startswith("acct_stmt"):
            header, _, rest = body.partition("\n")
            body = "  " + "  ,  ".join(header.split(",")) + "  \n" + rest
        tmp_path.joinpath(junk).write_text(body, encoding="utf-8")
    tmp_path.joinpath("notes.csv").write_text(
        "note,author\nring Priya about setl_9,ops\n", encoding="utf-8")
    return tmp_path


def test_every_file_is_identified_by_its_header_not_its_name(scruffy):
    found = detect(scruffy)
    assert not found.problems, found.problems
    assert set(found.mapping) == set(SCHEMAS)
    assert {name: path.name for name, path in found.mapping.items()} == SCRUFFY


def test_a_column_aligned_header_is_detected_and_loaded(scruffy):
    """The 2026-08-29 incident: an editor aligned the columns and all 46 rows were refused.

    Refusing was correct -- ingest could not find the columns. Stripping fieldnames means
    it can, so the file now loads. A genuinely absent column still fails loudly, which is
    what `test_missing_column_is_named` holds.
    """
    padded = scruffy.joinpath("acct_stmt_0904.csv").read_text(encoding="utf-8")
    assert padded.startswith("  txn_date  ,"), "fixture is not actually column-aligned"

    found = detect(scruffy)
    assert found.mapping["bank_statement.csv"].name == "acct_stmt_0904.csv"
    assert len(load(scruffy, found.mapping).bank) == 46


def test_the_stray_csv_is_skipped_never_guessed_at(scruffy):
    found = detect(scruffy)
    assert [path.name for path in found.skipped] == ["notes.csv"]


def test_scruffy_and_tidy_folders_load_to_the_same_ledger(scruffy):
    scruffed = load(scruffy, detect(scruffy).mapping)
    tidy = load(ROOT.joinpath("data", "heldout"))
    assert scruffed.counts() == tidy.counts()


def test_detection_says_which_columns_named_each_file(scruffy):
    """The table is evidence, not an assertion -- the same reason exceptions carry a rung."""
    for hit in detect(scruffy).found:
        assert hit.matched_on, f"{hit.path.name} was identified without saying why"
        assert set(hit.matched_on) <= set(SCHEMAS[hit.schema])


def test_a_missing_signature_names_the_schema_and_the_columns_it_needed(scruffy):
    scruffy.joinpath("settlement-report.csv").unlink()
    found = detect(scruffy)
    assert "settlements.csv" not in found.mapping
    assert any("settlements" in p and "net_amount_paise" in p for p in found.problems), \
        found.problems


def test_two_files_with_one_signature_are_a_choice_never_a_guess(scruffy):
    """A person knows which export they meant. Detection must not pick for them."""
    scruffy.joinpath("payments_v2_FINAL.csv").write_text(
        scruffy.joinpath("rzp_pmt_sep.csv").read_text(encoding="utf-8"), encoding="utf-8")
    found = detect(scruffy)
    assert "payments.csv" not in found.mapping, "detection picked one of two silently"
    assert {hit.path.name for hit in found.choices["payments.csv"]} == \
        {"rzp_pmt_sep.csv", "payments_v2_FINAL.csv"}


def test_one_file_matching_two_schemas_fails_rather_than_asking(tmp_path):
    """The other ambiguity, and it is ours not the user's.

    Two files for one schema is a real choice a human can make. One file satisfying two
    schemas means the required-column sets do not discriminate, and no answer the user
    gives fixes that -- they would be guessing at our schema definitions.
    """
    both = list(SCHEMAS["refunds.csv"]) + list(SCHEMAS["settlements.csv"])
    tmp_path.joinpath("everything.csv").write_text(
        ",".join(dict.fromkeys(both)) + "\n", encoding="utf-8")
    found = detect(tmp_path)
    assert not found.choices, "this is not a question to put to the user"
    assert any("everything.csv" in p and "refunds.csv" in p and "settlements.csv" in p
               for p in found.problems), found.problems


def test_a_padded_header_is_stripped_but_an_absent_column_still_fails(tmp_path):
    build(tmp_path)
    tidy = tmp_path.joinpath("orders.csv").read_text(encoding="utf-8")
    header, _, rest = tidy.partition("\n")
    tmp_path.joinpath("orders.csv").write_text(
        "  ,  ".join(header.split(",")) + "\n" + rest, encoding="utf-8")
    assert len(load(tmp_path).orders) == 2

    tmp_path.joinpath("orders.csv").write_text(
        tidy.replace("gross_amount_paise", "gross_amt"), encoding="utf-8")
    with pytest.raises(IngestError) as bad:
        load(tmp_path)
    assert "gross_amount_paise" in str(bad.value)

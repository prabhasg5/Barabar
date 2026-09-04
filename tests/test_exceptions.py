"""The exception classifier. PRD 6.

The tests here mostly guard against one failure: **a code that never fires reads exactly like
a code with no instances in the data.** Both show a zero. So every code the classifier is
supposed to raise has a test that it does raise, on both seeds, and the two codes it
deliberately does not raise are asserted to be deliberate rather than missing.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from exceptions import classify, known_gaps
from ingest.load import load
from match.ladder import run

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ["train", "heldout"]

# Everything in PRD 6's table except the two known_gaps codes. E05 belongs to step 8's audit
# and E11 is not detectable from the CSVs at all -- both are asserted separately below.
RAISED = ["E01", "E02", "E03", "E04", "E06", "E07", "E08", "E09", "E10", "E12", "E13", "E14"]


@pytest.fixture(scope="module", params=SEEDS)
def run_of(request):
    ledger = load(ROOT.joinpath("data", request.param))
    result = run(ledger, through="R2")
    exceptions, unclassified = classify(ledger, result)
    truth = json.loads(ROOT.joinpath("eval", "ground_truth", f"{request.param}.json")
                       .read_text(encoding="utf-8"))
    return request.param, ledger, result, exceptions, unclassified, truth


def test_every_raisable_code_fires_on_both_seeds(run_of):
    """The empty-class guard, and the whole reason this file exists.

    A classifier that never reaches a code reports zero for it, which is indistinguishable
    from a dataset that contains none. PRD 6 requires the generator to make every code, so
    every code must come out the far side -- E04 excepted where the answer key has none that
    is not also an E01; see the seed-specific assertion below.
    """
    name, _, _, exceptions, _, _ = run_of
    seen = Counter(e.code for e in exceptions)
    missing = [c for c in RAISED if not seen[c]]
    if name == "heldout":
        # Held-out's only E04 label sits on a row that is also an E01 -- an invented credit
        # the generator then drifted. A credit with no settlement cannot be an amount
        # mismatch against one, so the classifier calls it E01 and there is no E04 to find.
        missing = [c for c in missing if c != "E04"]
    assert not missing, f"{name}: these codes never fired and would read as clean zeros: {missing}"


def test_e03_comes_from_the_ladder_and_matches_its_flagged_set(run_of):
    """E03 attaches to a match that SUCCEEDED, so a classifier walking unmatched records
    alone can never reach it. It is raised from `Result.flagged`, and this asserts the two
    are the same set rather than merely the same count -- equal counts of different records
    would pass a count check and be wrong."""
    _, _, result, exceptions, _, truth = run_of
    emitted = {e.record_id for e in exceptions if e.code == "E03"}
    assert emitted == {m.bank_ref for m in result.flagged}
    assert emitted == {b["record_id"] for b in truth["breaks"] if b["code"] == "E03"}


def test_the_codes_we_do_not_raise_are_deliberate_and_absent(run_of):
    """known_gaps() is the difference between "did not occur" and "cannot be seen"."""
    _, _, _, exceptions, _, truth = run_of
    gaps = known_gaps()
    assert set(gaps) == {"E11"}, (
        "E05 left this set at step 8 when audit.fees took ownership of it. E11 is the only "
        "code that stays -- it is undetectable from these sources, not merely unimplemented.")
    emitted = {e.code for e in exceptions}
    assert not emitted & set(gaps), "a code listed as not raised was raised"
    labelled = {b["code"] for b in truth["breaks"]}
    assert set(gaps) <= labelled, "a gap is claimed for a code the generator never makes"


def test_e14_is_the_only_thing_that_is_not_a_break(run_of):
    """PRD 6: is_break separates 'something is wrong' from 'one question settles it'."""
    _, _, _, exceptions, _, _ = run_of
    assert {e.code for e in exceptions if not e.is_break} <= {"E14"}
    assert [e for e in exceptions if e.code == "E14" and e.is_break] == []


def test_no_record_is_both_classified_and_unclassified(run_of):
    """Unclassified means evidence ran out. Emitting a code for the same record as well
    would make the count a decoration rather than a statement about the run."""
    _, _, _, exceptions, unclassified, _ = run_of
    coded = {e.record_id for e in exceptions} | {e.other_id for e in exceptions if e.other_id}
    assert not coded & {rid for _, rid in unclassified}


def test_an_unreadable_narration_is_e13_when_matched_and_e01_when_not(run_of):
    """The two differ only in whether anything ties to the money, which is a fact about the
    match rather than about the string. Getting it backwards would report real settlements as
    unidentified receipts and overstate missing money.

    Asserted against the ANSWER KEY's sets, not against `AGGREGATOR`. The first version of
    this test imported that constant and checked the classifier agreed with itself, so
    changing "RAZORPAY" to "NEFT" left all eighteen tests green -- a tautology of exactly the
    shape CLAUDE.md's watch-it-fail rule exists to catch, caught by that rule.
    """
    name, _, _, exceptions, _, truth = run_of
    labelled = {}
    for b in truth["breaks"]:
        labelled.setdefault(b["code"], set()).add(b["record_id"])
    assert {e.record_id for e in exceptions if e.code == "E13"} == labelled["E13"]
    # Held-out's second E01 also carries an E04 label; the classifier calls it E01, which is
    # the only code that can be true of a credit no settlement backs.
    assert {e.record_id for e in exceptions if e.code == "E01"} == labelled["E01"]


def test_e02_and_e12_split_on_the_statement_period_not_on_the_match(run_of):
    """The only thing separating them is the date, so this asserts the boundary is the one
    the engine derives from the bank statement -- not one borrowed from the answer key."""
    _, ledger, _, exceptions, _, _ = run_of
    period_end = max(row["txn_date"] for row in ledger.bank)
    settled = {s["settlement_id"]: s["settled_at"] for s in ledger.settlements}
    for e in exceptions:
        if e.code == "E12":
            assert settled[e.record_id] > period_end
        if e.code == "E02":
            assert settled[e.record_id] <= period_end


def test_in_transit_is_derivable_without_the_answer_key(run_of):
    """Retires the step 5 borrow. If this fails, `unexplained` is again a number the engine
    could not produce on a real merchant's files."""
    _, ledger, _, _, _, truth = run_of
    period_end = max(row["txn_date"] for row in ledger.bank)
    derived = sum(s["net_amount_paise"] for s in ledger.settlements
                  if s["settled_at"] > period_end)
    assert derived == truth["totals"]["in_transit_paise"]


def test_every_exception_carries_a_reason_and_a_rung(run_of):
    """PRD 6: code, both ids, delta, the rung that gave up, one sentence of English."""
    _, _, _, exceptions, _, _ = run_of
    for e in exceptions:
        assert e.reason.strip() and e.reason.strip()[-1] in ".!", e
        assert e.rung, e
        assert e.record_id, e

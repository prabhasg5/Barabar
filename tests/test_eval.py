"""The harness that scores the engine. Tests here guard the scoring rule itself --
a scorer that is generous is worse than no scorer, because it reports a number nobody
can act on.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from ingest.load import load
from match.ladder import Match, Result, run

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "harness", ROOT.joinpath("eval", "harness.py"))
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


class FakeLedger:
    """The three collections the scorer reads. Not a Ledger -- it needs no CSVs."""

    def __init__(self, bank, settlements, payments):
        self.bank = bank
        self.settlements = settlements
        self.payments = payments
        self.refunds = []
        self.orders = []


def ledger(credits=((("HDFC1"), 1000),), settlements=(("setl_1", 1000),), payments=("pay_1",)):
    return FakeLedger(
        bank=[{"bank_ref": ref, "credit_paise": amount} for ref, amount in credits],
        settlements=[{"settlement_id": sid, "net_amount_paise": net,
                      "adjustment_paise": 0} for sid, net in settlements],
        payments=[{"payment_id": pid, "amount_paise": 0, "fee_paise": 0, "gst_paise": 0}
                  for pid in payments],
    )


def truth_of(matches, totals=None, ambiguous=()):
    return {"seed": 1, "matches": matches, "ambiguous": list(ambiguous),
            "totals": totals or {"gross_paise": 0, "fee_paise": 0, "gst_paise": 0,
                                 "refund_paise": 0, "adjustment_paise": 0,
                                 "credit_paise": 0, "in_transit_paise": 0}}


@pytest.mark.parametrize("part, whole, expected", [
    (3514, 5000, 7028),
    (1, 3, 3333),
    (2, 3, 6667),          # rounds half away from zero, not toward it
    (1, 2, 5000),
    (0, 5000, 0),
    (5, 0, 0),             # no whole, no ratio, no ZeroDivisionError
    (44, 44, 10000),
])
def test_bps_is_integer_and_rounds_half_away(part, whole, expected):
    assert harness.bps(part, whole) == expected


def test_a_match_missing_one_payment_is_a_false_positive():
    """PRD 8: the match is the unit. Four of five right is one wrong match, not four right."""
    led = ledger(payments=("pay_1", "pay_2", "pay_3", "pay_4", "pay_5"))
    result = Result(matches=[Match("HDFC1", ("setl_1",),
                                   ("pay_1", "pay_2", "pay_3", "pay_4"), "R0", 0)])
    truth = truth_of([{"bank_ref": "HDFC1", "settlement_ids": ["setl_1"],
                       "payment_ids": ["pay_1", "pay_2", "pay_3", "pay_4", "pay_5"]}])
    metrics = harness.score(led, result, truth, run_ms=0, residue=0)
    assert metrics["matches_correct"] == 0
    assert metrics["precision_bps"] == 0
    assert metrics["recall_bps"] == 0


def test_an_exact_match_scores_clean_regardless_of_payment_order():
    led = ledger(payments=("pay_1", "pay_2"))
    result = Result(matches=[Match("HDFC1", ("setl_1",), ("pay_2", "pay_1"), "R0", 0)])
    truth = truth_of([{"bank_ref": "HDFC1", "settlement_ids": ["setl_1"],
                       "payment_ids": ["pay_1", "pay_2"]}])
    metrics = harness.score(led, result, truth, run_ms=0, residue=0)
    assert metrics["precision_bps"] == 10000 and metrics["recall_bps"] == 10000
    assert metrics["payment_coverage_bps"] == 10000


def test_a_match_on_the_wrong_credit_is_a_false_positive():
    led = ledger(credits=(("HDFC1", 1000), ("HDFC2", 1000)))
    result = Result(matches=[Match("HDFC2", ("setl_1",), ("pay_1",), "R1", 0)])
    truth = truth_of([{"bank_ref": "HDFC1", "settlement_ids": ["setl_1"],
                       "payment_ids": ["pay_1"]}])
    metrics = harness.score(led, result, truth, run_ms=0, residue=0)
    assert metrics["matches_claimed"] == 1 and metrics["matches_correct"] == 0


def test_conservation_fails_when_the_ledger_loses_money():
    led = ledger(payments=("pay_1",))
    led.payments[0]["amount_paise"] = 500
    truth = truth_of([], totals={"gross_paise": 900, "fee_paise": 0, "gst_paise": 0,
                                 "refund_paise": 0, "adjustment_paise": 0,
                                 "credit_paise": 1000, "in_transit_paise": 0})
    with pytest.raises(AssertionError, match="does not reproduce"):
        harness.check_conservation(led, truth)


def test_conservation_returns_the_residue_rather_than_hiding_it():
    """Injected breaks leave money that does not tie. That is the finding, not an error."""
    led = ledger(payments=("pay_1",))
    led.payments[0]["amount_paise"] = 1200
    truth = truth_of([], totals={"gross_paise": 1200, "fee_paise": 0, "gst_paise": 0,
                                 "refund_paise": 0, "adjustment_paise": 0,
                                 "credit_paise": 1000, "in_transit_paise": 0})
    assert harness.check_conservation(led, truth) == 200


def test_partition_fails_when_a_credit_ends_in_no_state():
    led = ledger(credits=(("HDFC1", 1000), ("HDFC2", 700)))
    result = Result(matches=[Match("HDFC1", ("setl_1",), ("pay_1",), "R0", 0)],
                    unmatched_credits=[], unmatched_settlements=[])
    with pytest.raises(AssertionError, match="no state at all"):
        harness.check_partition(led, result)


def test_partition_fails_when_a_credit_is_matched_and_open_at_once():
    led = ledger()
    result = Result(matches=[Match("HDFC1", ("setl_1",), ("pay_1",), "R0", 0)],
                    unmatched_credits=["HDFC1"], unmatched_settlements=[])
    with pytest.raises(AssertionError, match="two states"):
        harness.check_partition(led, result)


def test_partition_passes_on_a_clean_split():
    led = ledger(credits=(("HDFC1", 1000), ("HDFC2", 700)),
                 settlements=(("setl_1", 1000), ("setl_2", 700)))
    result = Result(matches=[Match("HDFC1", ("setl_1",), ("pay_1",), "R0", 0)],
                    unmatched_credits=["HDFC2"], unmatched_settlements=["setl_2"])
    harness.check_partition(led, result)


def test_results_json_keeps_the_earlier_rung_baseline(tmp_path, monkeypatch):
    """Acceptance criterion 9: step 6 must not overwrite the number it is measured against."""
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    tmp_path.joinpath("eval").mkdir()
    harness.write_results("heldout", {"rungs": "R0+R1", "match_rate_bps": 8043})
    harness.write_results("heldout", {"rungs": "R0+R1+R2", "match_rate_bps": 9500})
    written = json.loads(tmp_path.joinpath("eval", "results.json").read_text())
    assert written["heldout"]["R0+R1"]["match_rate_bps"] == 8043
    assert written["heldout"]["R0+R1+R2"]["match_rate_bps"] == 9500


def test_heldout_precision_is_perfect_and_the_run_is_reproducible():
    """The held-out set, opened at step 5 -- one of the four moments PRD 8 allows."""
    if not ROOT.joinpath("data", "heldout").exists():
        pytest.skip("run: PYTHONPATH=src python -m generate heldout")
    first = harness.evaluate("heldout")
    second = harness.evaluate("heldout")
    assert first["precision_bps"] == 10000
    assert {k: v for k, v in first.items() if k != "run_ms"} == \
           {k: v for k, v in second.items() if k != "run_ms"}


# The four codes that move `credit_paise` with no matching movement on the ledger side:
# E01 invents a credit, E02 deletes one, E03 and E04 drift one. Every other code either moves
# both sides together (E05 fee, E10 duplicate, E11 partial refund) or moves no money at all
# (E06-E09, E12, E13). This split is a property of the taxonomy, not a measurement of a run.
BANK_SIDE_CODES = {"E01", "E02", "E03", "E04"}


@pytest.mark.parametrize("name", ["train", "heldout"])
def test_the_identity_residue_is_exactly_the_bank_side_breaks(name):
    """PRD 8's identity does not close on injured data, and this is what the gap is.

    gross - fee - gst - refund + adjustment - in_transit  vs  credit

    The gap was assumed at step 5 to be "the injected breaks" and never measured; the data
    was regenerated twice after that. Measured on 2026-09-01 it ties to the paisa on both
    seeds, and the reason is structural: a break that moves the bank side alone leaves the
    left-hand side untouched, so it shows up in the residue at exactly its own delta and
    with the opposite sign. A break that moves both sides nets to zero and cannot appear.

    This is the assertion the step 7 classifier's completeness rests on. If it stops holding,
    the identity no longer closes and no classifier built on it can be shown to be complete
    -- so this fails loudly rather than reporting a residue nobody can attribute.
    """
    ledger = load(ROOT.joinpath("data", name))
    truth = json.loads(
        ROOT.joinpath("eval", "ground_truth", f"{name}.json").read_text(encoding="utf-8"))

    residue = harness.check_conservation(ledger, truth)
    bank_side = sum(b["delta_paise"] for b in truth["breaks"]
                    if b["code"] in BANK_SIDE_CODES)
    assert residue == -bank_side, (
        f"{name}: identity residue is {residue} paise but the bank-side breaks account for "
        f"{-bank_side}. {residue + bank_side} paise are unattributed -- the identity no "
        f"longer closes and step 7's completeness cannot be tested.")


@pytest.mark.parametrize("name", ["train", "heldout"])
def test_every_other_code_moves_both_sides_or_none(name):
    """The other half of the same claim, asserted separately so a failure says which half.

    If a both-sides code ever moved the residue, the test above would still pass whenever
    two such codes happened to cancel. This one removes that hiding place: rebuild the
    residue from the ledger with the bank-side breaks reversed out, and it must be zero.
    """
    ledger = load(ROOT.joinpath("data", name))
    truth = json.loads(
        ROOT.joinpath("eval", "ground_truth", f"{name}.json").read_text(encoding="utf-8"))

    residue = harness.check_conservation(ledger, truth)
    for b in truth["breaks"]:
        if b["code"] in BANK_SIDE_CODES:
            residue += b["delta_paise"]
    assert residue == 0, (
        f"{name}: {residue} paise of the identity gap come from codes that are supposed to "
        f"move both sides equally. One of them is moving money on one side only.")


@pytest.mark.parametrize("name", ["train", "heldout"])
def test_the_coverage_split_accounts_for_every_payment(name):
    """The three buckets must partition the payments, with nothing falling between them.

    A payment that reaches no code would quietly shrink `still_open` and flatter the split --
    the coverage number would still be right while its explanation was incomplete, which is
    the reading the split exists to prevent.
    """
    ledger = load(ROOT.joinpath("data", name))
    result = run(ledger, through="R2")
    from exceptions import classify
    split = harness.coverage_split(ledger, result, classify(ledger, result)[0])

    assert split["reconciled"] + split["in_transit"] + split["still_open"] == \
        split["payments_total"], "the three buckets do not sum to the payments ingested"
    assert not split["by_code"].get("unattributed"), \
        f"{split['by_code'].get('unattributed')} uncovered payments reached no exception code"
    assert sum(split["by_code"].values()) == \
        split["payments_total"] - split["reconciled"], \
        "the per-code breakdown does not add up to the uncovered payments"
    # in transit is E12 and only E12: if another code leaks in here, a real break gets
    # reported as a normal period-end state, which is the one direction that must not happen.
    assert split["in_transit"] == split["by_code"].get("E12", 0)


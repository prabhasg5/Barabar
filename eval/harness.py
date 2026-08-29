"""Score the matching engine against the answer key and write eval/results.json.

    PYTHONPATH=src uv run python eval/harness.py train
    PYTHONPATH=src uv run python eval/harness.py heldout

This file is the only thing that opens `eval/ground_truth/`. Nothing under `src/` may --
that is PRD 8's anti-circularity rule, asserted by
tests/test_match.py::test_the_engine_never_reads_the_ground_truth_file.

A match is scored whole. The engine's payment_ids set must equal the answer key's set for
that bank_ref exactly; four payments right out of five is one false positive, not four true
positives. Every ratio here is an integer in basis points for the same reason money is
integer paise -- see DECISIONS.md, "No exemption for ratios either".
"""

import json
import sys
import time
from pathlib import Path

from ingest.load import IngestError, load
from match.ladder import run
from money import Paise, format_rupees

ROOT = Path(__file__).resolve().parents[1]
RUNGS = "R0+R1"      # bumped as rungs land; results.json is keyed by this


def bps(part: int, whole: int) -> int:
    """A ratio in basis points, rounded half away from zero. 3514 of 5000 -> 7028."""
    if whole == 0:
        return 0
    sign = -1 if part < 0 else 1
    return sign * ((abs(part) * 1000000 + whole * 50) // (whole * 100))


def show_bps(rate: int) -> str:
    return f"{rate // 100}.{abs(rate) % 100:02d}%"


def totals_of(ledger) -> dict[str, int]:
    """Recompute the answer key's totals from the CSVs alone.

    Mirrors src/generate/world.totals field for field, including the detail that an
    unlinked refund carries no settlement_id and therefore no money out of a batch.
    """
    return {
        "gross_paise": sum(p["amount_paise"] for p in ledger.payments),
        "fee_paise": sum(p["fee_paise"] for p in ledger.payments),
        "gst_paise": sum(p["gst_paise"] for p in ledger.payments),
        "refund_paise": sum(r["amount_paise"] for r in ledger.refunds if r["settlement_id"]),
        "adjustment_paise": sum(s["adjustment_paise"] for s in ledger.settlements),
        "credit_paise": sum(b["credit_paise"] for b in ledger.bank),
    }


def check_conservation(ledger, truth: dict) -> int:
    """No money may go missing between the generator and the loaded ledger.

    Asserts the six CSV-derivable totals reproduce the answer key exactly, then returns
    the identity residue: what PRD 8's equation leaves over once the injected breaks have
    moved money that no longer ties. That residue is the damage the exception classifier
    has to account for at step 7; it is reported, not asserted to zero, because at this
    step nothing can yet attribute it.
    """
    mine, theirs = totals_of(ledger), truth["totals"]
    off = {k: mine[k] - theirs[k] for k in mine if mine[k] != theirs[k]}
    assert not off, f"the ledger does not reproduce the answer key's totals: {off}"

    left = (mine["gross_paise"] - mine["fee_paise"] - mine["gst_paise"]
            - mine["refund_paise"] + mine["adjustment_paise"]
            - theirs["in_transit_paise"])
    return left - mine["credit_paise"]


def check_partition(ledger, result) -> None:
    """Acceptance criterion 3, for the records the ladder touches.

    Every bank credit and every settlement ends in exactly one state, and the rupees in
    each state add back to the rupees ingested. A reconciler whose states do not sum is
    worse than no reconciler.
    """
    matched_refs = {m.bank_ref for m in result.matches}
    matched_sids = {sid for m in result.matches for sid in m.settlement_ids}

    assert not matched_refs & set(result.unmatched_credits), "a credit is in two states"
    assert not matched_sids & set(result.unmatched_settlements), "a settlement is in two states"
    assert matched_refs | set(result.unmatched_credits) == {b["bank_ref"] for b in ledger.bank}, \
        "a bank credit ended in no state at all"
    assert matched_sids | set(result.unmatched_settlements) == \
        {s["settlement_id"] for s in ledger.settlements}, "a settlement ended in no state at all"

    credit = {b["bank_ref"]: b["credit_paise"] for b in ledger.bank}
    split = (sum(credit[r] for r in matched_refs)
             + sum(credit[r] for r in result.unmatched_credits))
    assert split == sum(credit.values()), f"credit rupees do not partition: {split}"


def score(ledger, result, truth: dict, run_ms: int, residue: int) -> dict:
    key = {m["bank_ref"]: set(m["payment_ids"]) for m in truth["matches"]}
    correct = [m for m in result.matches if key.get(m.bank_ref) == set(m.payment_ids)]

    credit = {b["bank_ref"]: b["credit_paise"] for b in ledger.bank}
    net = {s["settlement_id"]: s["net_amount_paise"] for s in ledger.settlements}
    covered = {pid for m in result.matches for pid in m.payment_ids}

    return {
        "rungs": RUNGS,
        "seed": truth["seed"],
        "credits_total": len(ledger.bank),
        "credits_matched": len(result.matches),
        "credits_unmatched": len(result.unmatched_credits),
        "settlements_total": len(ledger.settlements),
        "settlements_unmatched": len(result.unmatched_settlements),
        "matches_claimed": len(result.matches),
        "matches_correct": len(correct),
        "matches_expected": len(truth["matches"]),
        "precision_bps": bps(len(correct), len(result.matches)),
        "recall_bps": bps(len(correct), len(truth["matches"])),
        "match_rate_bps": bps(len(result.matches), len(ledger.bank)),
        "rung_attribution": result.by_rung(),
        "payments_total": len(ledger.payments),
        "payments_covered": len(covered),
        "payment_coverage_bps": bps(len(covered), len(ledger.payments)),
        "reconciled_paise": sum(credit[m.bank_ref] for m in result.matches),
        "open_credit_paise": sum(credit[r] for r in result.unmatched_credits),
        "open_settlement_paise": sum(net[s] for s in result.unmatched_settlements),
        "drift_paise": int(result.drift_paise),
        "drift_matches": len(result.flagged),
        "unexplained_paise": residue,
        "model_cost_paise": 0,
        "run_ms": run_ms,
    }


def report(name: str, m: dict) -> None:
    print(f"{name}  seed {m['seed']}  rungs {m['rungs']}\n")
    print(f"  auto-match rate     {show_bps(m['match_rate_bps']):>9}   "
          f"{m['credits_matched']} of {m['credits_total']} bank credits")
    print(f"  precision           {show_bps(m['precision_bps']):>9}   "
          f"{m['matches_correct']} correct of {m['matches_claimed']} claimed")
    print(f"  recall              {show_bps(m['recall_bps']):>9}   "
          f"{m['matches_correct']} of {m['matches_expected']} real matches")
    print(f"  payments covered    {show_bps(m['payment_coverage_bps']):>9}   "
          f"{m['payments_covered']} of {m['payments_total']}")
    print("\n  -- how it was matched --")
    for rung, count in m["rung_attribution"].items():
        print(f"  {rung}  {count:5d} credits   "
              f"{show_bps(bps(count, m['credits_total'])):>8}")
    print(f"\n  reconciled          {format_rupees(Paise(m['reconciled_paise'])):>16}")
    print(f"  open, received      {format_rupees(Paise(m['open_credit_paise'])):>16}   "
          f"{m['credits_unmatched']} credits nothing explains")
    print(f"  open, expected      {format_rupees(Paise(m['open_settlement_paise'])):>16}   "
          f"{m['settlements_unmatched']} settlements with no credit")
    print(f"  drift absorbed      {format_rupees(Paise(m['drift_paise'])):>16}   "
          f"{m['drift_matches']} matches consumed tolerance")
    print(f"  unexplained         {format_rupees(Paise(m['unexplained_paise'])):>16}   "
          f"identity residue -- attribution is step 7")
    print(f"\n  run took {m['run_ms']}ms  ·  model cost "
          f"{format_rupees(Paise(m['model_cost_paise']))}")
    if m["drift_paise"] > 10000:
        print(f"\n  ** absorbed drift is over 100 rupees this run. **")


def evaluate(name: str) -> dict:
    ledger = load(ROOT.joinpath("data", name))
    truth = json.loads(
        ROOT.joinpath("eval", "ground_truth", f"{name}.json").read_text(encoding="utf-8"))

    started = time.monotonic_ns()
    result = run(ledger)
    run_ms = (time.monotonic_ns() - started) // 1000000

    residue = check_conservation(ledger, truth)
    check_partition(ledger, result)
    return score(ledger, result, truth, run_ms, residue)


def write_results(name: str, metrics: dict) -> Path:
    """Keyed by set, then by which rungs were enabled, so before/after survives.

    Acceptance criterion 9 wants R2's and R3's before/after in here. Keying on the rung
    set means step 6 writing "R0+R1+R2" cannot overwrite the baseline it is measured
    against, and no field has to be special-cased to hold a previous number.
    """
    path = ROOT.joinpath("eval", "results.json")
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.setdefault(name, {})[metrics["rungs"]] = metrics
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    names = sys.argv[1:] or ["train"]
    for name in names:
        try:
            metrics = evaluate(name)
        except IngestError as bad:
            print(f"{len(bad.problems)} rows could not be read. Nothing was loaded.\n")
            for problem in bad.problems:
                print(f"  {problem}")
            sys.exit(1)
        report(name, metrics)
        print(f"\n  written to {write_results(name, metrics).relative_to(ROOT)}\n")

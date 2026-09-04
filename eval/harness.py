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
from audit.fees import audit_fees, refund_fee_burden, totals as fee_totals
from exceptions import classify, known_gaps
from match.ladder import run
from money import Paise, format_rupees

ROOT = Path(__file__).resolve().parents[1]
RUNGS = "R0+R1+R2"   # bumped as rungs land; results.json is keyed by this
R3_RUNGS = "R0+R1+R2+R3"


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
    """PRD 8: an `ambiguous` credit is scored as a refusal, not as a match.

    Two or more subsets of settlements tie to it exactly, so the correct behaviour is E14
    listing every candidate. A claim on one counts as a false match **even when the payment
    set matches `true_subset`** -- the engine had no evidence to justify choosing it and
    would have been wrong as often as not on data the generator did not label. Guessing
    correctly is not knowing, and a scorer that rewarded the guess would teach the solver to
    guess. So an ambiguous credit is out of the recall denominator and a claim on it lands
    in the precision denominator without ever reaching the numerator.
    """
    refuse = {a["bank_ref"] for a in truth["ambiguous"]}
    key = {m["bank_ref"]: set(m["payment_ids"]) for m in truth["matches"]}
    expected = [m for m in truth["matches"] if m["bank_ref"] not in refuse]
    correct = [m for m in result.matches
               if m.bank_ref not in refuse and key.get(m.bank_ref) == set(m.payment_ids)]
    bundled = sum(1 for m in truth["matches"] if len(m["settlement_ids"]) > 1)

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
        "matches_expected": len(expected),
        # Printed under precision on every run. The denominator is ~45 whole matches, so a
        # single false match moves the figure by more than two points: 100.00% here is not
        # distinguishable from the next value down, and quoting it bare invites exactly that
        # reading. The caveat reprints so it cannot be separated from the number it qualifies
        # -- same reasoning as the thin-support list under the confusion matrix.
        "precision_one_wrong_bps": bps(max(0, len(correct) - 1), len(result.matches))
        if result.matches else 0,
        "ambiguous_total": len(refuse),
        "ambiguous_claimed": sum(1 for m in result.matches if m.bank_ref in refuse),
        "bundled_credits": bundled,
        "ambiguity_rate_bps": bps(len(refuse), bundled),
        "precision_bps": bps(len(correct), len(result.matches)),
        "recall_bps": bps(len(correct), len(expected)),
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


def coverage_split(ledger, result, exceptions) -> dict:
    """Where every uncovered payment went, by the code that explains its settlement.

    **The strict number still leads.** "Reconciled to bank" is the only figure that means the
    money is tied to a bank credit, and no split is allowed to soften it -- a merchant asking
    "can I sign off" is asking that number.

    But a single figure of 88.73% invites the reading that 11.27% is wrong, and it is not. A
    settlement that lands after the statement closes is in transit: correctly accounted for,
    not yet in a bank credit, and a normal state at period end rather than a gap. Reporting it
    inside the same number as money that never arrived conflates a clock with a break.

    Measured before this was built rather than assumed *(train+heldout, 6b, 2026-09-01)*:
    in transit is 31% of the train gap and 40% of held-out -- large, and not the bulk. The
    rest is real: E02 money that never arrived, E04 money that arrived wrong, and E14 a
    question awaiting an answer. So the split is worth reporting and does not rescue the
    number, which is the honest outcome and the reason to print all three.
    """
    code_of: dict[str, set] = {}
    for e in exceptions:
        code_of.setdefault(e.record_id, set()).add(e.code)
    spoken_for = {sid for a in result.ambiguous for c in a.candidates for sid in c}
    paired = {e.other_id for e in exceptions if e.code == "E04" and e.other_id}

    covered = {pid for m in result.matches for pid in m.payment_ids}
    by_code: dict[str, int] = {}
    for p in ledger.payments:
        if p["payment_id"] in covered:
            continue
        sid = p["settlement_id"]
        codes = code_of.get(sid, set()) if sid else set()
        if codes:
            label = "/".join(sorted(codes))
        elif sid in spoken_for:
            label = "E14"
        elif sid in paired:
            label = "E04"
        elif not sid:
            label = "no settlement"
        else:
            label = "unattributed"
        by_code[label] = by_code.get(label, 0) + 1

    total = len(ledger.payments)
    in_transit = by_code.get("E12", 0)
    still_open = total - len(covered) - in_transit
    return {
        "payments_total": total,
        "reconciled": len(covered),
        "reconciled_bps": bps(len(covered), total),
        "in_transit": in_transit,
        "in_transit_bps": bps(in_transit, total),
        "still_open": still_open,
        "still_open_bps": bps(still_open, total),
        "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
    }


def report_coverage_split(c: dict) -> None:
    print("\n  -- where the payments are --")
    print(f"  reconciled to bank  {show_bps(c['reconciled_bps']):>9}   "
          f"{c['reconciled']} of {c['payments_total']}   tied to a bank credit. "
          f"THIS is the sign-off number.")
    print(f"  in transit          {show_bps(c['in_transit_bps']):>9}   "
          f"{c['in_transit']} payments   settled after the statement closed -- normal at "
          f"period end, not a gap")
    print(f"  still open          {show_bps(c['still_open_bps']):>9}   "
          f"{c['still_open']} payments   and this is not one thing:")
    for code, n in c["by_code"].items():
        if code == "E12":
            continue
        print(f"      {code:<6}{n:>6}   {show_bps(bps(n, c['payments_total'])):>7}")
    if c["by_code"].get("unattributed"):
        print(f"  ** {c['by_code']['unattributed']} payments in the gap reached no code **")


def score_exceptions(ledger, result, truth: dict) -> dict:
    """Per-code confusion, with support. **Not rupee-weighted, deliberately.**

    E01 and E02 are ~99.9% of the identity gap on both seeds, so any money-weighted score is
    four rows in a trenchcoat -- it would read as broad accuracy while saying nothing about
    the other ten codes. The classifier's job is assigning the right code; the rupee figure
    belongs in the identity check, where it means something. See DECISIONS.md, 2026-08-31.

    A record may legitimately carry more than one true code -- a credit can be both drifted
    and unreadable -- so a prediction is correct when its code is *among* that record's true
    codes, and `support` counts label instances rather than records.
    """
    true_codes: dict[str, set] = {}
    for b in truth["breaks"]:
        true_codes.setdefault(b["record_id"], set()).add(b["code"])
    for a in truth["ambiguous"]:
        true_codes.setdefault(a["bank_ref"], set()).add("E14")

    support: dict[str, int] = {}
    for codes in true_codes.values():
        for c in codes:
            support[c] = support.get(c, 0) + 1

    predicted: dict[str, int] = {}
    correct: dict[str, int] = {}
    confused: dict[str, dict[str, int]] = {}
    for e in classify(ledger, result)[0]:
        ids = [e.record_id] + ([e.other_id] if e.other_id else [])
        actual = set()
        for i in ids:
            actual |= true_codes.get(i, set())
        predicted[e.code] = predicted.get(e.code, 0) + 1
        if e.code in actual:
            correct[e.code] = correct.get(e.code, 0) + 1
        else:
            label = ",".join(sorted(actual)) or "(unlabelled)"
            confused.setdefault(e.code, {})[label] = \
                confused.setdefault(e.code, {}).get(label, 0) + 1

    gaps = known_gaps()
    return {
        "support": support, "predicted": predicted, "correct": correct,
        "confused": confused, "not_raised": sorted(gaps),
        "unclassified": len(classify(ledger, result)[1]),
        "codes_scored": sorted(set(support) - set(gaps)),
    }


def report_exceptions(x: dict) -> None:
    print("\n  -- exceptions, by code --")
    print(f"  {'code':<6}{'found':>7}{'true':>6}{'right':>7}   note")
    for code in sorted(set(x["support"]) | set(x["predicted"])):
        sup, pred = x["support"].get(code, 0), x["predicted"].get(code, 0)
        hit = x["correct"].get(code, 0)
        if code in x["not_raised"]:
            note = "not raised -- see known_gaps()"
        else:
            note = ""
            if x["confused"].get(code):
                note += f"false: {x['confused'][code]}  "
            if sup > hit:
                note += f"missed {sup - hit}"
            if sup and sup <= 3 and not note:
                note = "support too small to claim anything"
        print(f"  {code:<6}{pred:>7}{sup:>6}{hit:>7}   {note}")
    thin = [c for c in x["codes_scored"] if x["support"].get(c, 0) <= 3]
    print(f"\n  unclassified        {x['unclassified']:>9}   records the rules could not code")
    print(f"  codes with support <= 3   {' '.join(thin) or 'none':<20}"
          f"   too few rows to claim a rate")


def report_fees(f: dict, burden: dict) -> None:
    """PRD 7's headline, and the second number beside it.

    Over and under are printed separately and the net third. A single net figure lets an
    overcharge and an undercharge cancel into "no finding", which is the cancellation hiding
    place the second identity test exists to close.
    """
    print("\n  -- fee variance vs contract (E05) --")
    print(f"  overcharged     {format_rupees(Paise(f['overcharged_paise'])):>16}   "
          f"{f['overcharged_count']} payments")
    print(f"  undercharged    {format_rupees(Paise(f['undercharged_paise'])):>16}   "
          f"{f['undercharged_count']} payments")
    print(f"  net             {format_rupees(Paise(f['net_paise'])):>16}   "
          f"{f['payments']} payments off contract  (net alone hides cancellation; "
          f"the two above are the finding)")
    print("\n  -- fee paid on refunded revenue --   not a variance, not an exception")
    print(f"  fee + GST       {format_rupees(Paise(burden['total_paise'])):>16}   "
          f"{burden['refunds_joined']} refunds joined to a payment")
    print(f"                                     MDR is not reversed on refunds in India, so "
          f"this is correctly charged")
    print(f"                                     on revenue that was given back. Nothing to "
          f"dispute -- only to see.")


def report(name: str, m: dict) -> None:
    print(f"{name}  seed {m['seed']}  rungs {m['rungs']}\n")
    print(f"  auto-match rate     {show_bps(m['match_rate_bps']):>9}   "
          f"{m['credits_matched']} of {m['credits_total']} bank credits")
    print(f"  precision           {show_bps(m['precision_bps']):>9}   "
          f"{m['matches_correct']} correct of {m['matches_claimed']} claimed")
    print(f"                                  one wrong match here would read "
          f"{show_bps(m['precision_one_wrong_bps'])} -- a denominator of "
          f"{m['matches_claimed']}, not a rate")
    print(f"  recall              {show_bps(m['recall_bps']):>9}   "
          f"{m['matches_correct']} of {m['matches_expected']} real matches")
    print(f"  payments covered    {show_bps(m['payment_coverage_bps']):>9}   "
          f"{m['payments_covered']} of {m['payments_total']}")
    print(f"  ambiguity rate      {show_bps(m['ambiguity_rate_bps']):>9}   "
          f"{m['ambiguous_total']} of {m['bundled_credits']} bundled credits have a rival subset")
    if m["ambiguous_claimed"]:
        print(f"  ** {m['ambiguous_claimed']} match(es) claimed on an ambiguous credit -- "
              f"a guess, scored as false **")
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
          f"identity residue -- all of it E01/E02/E03/E04, asserted by test_eval")
    print(f"\n  run took {m['run_ms']}ms  ·  model cost "
          f"{format_rupees(Paise(m['model_cost_paise']))}")
    if m["drift_paise"] > 10000:
        print(f"\n  ** absorbed drift is over 100 rupees this run. **")


def report_r3(result, provider: str) -> None:
    """R3's own numbers. Token counts are printed beside the zero cost deliberately.

    `model_cost_paise: 0` alone reads like an unwired field. With the tokens next to it, it
    reads as what it is -- a free tier -- and the cost at any provider's rate is one
    multiplication away.
    """
    accepted = [m for m in result.matches if m.rung == "R3"]
    prompt_tokens = sum(p.prompt_tokens for p in result.proposals)
    completion_tokens = sum(p.completion_tokens for p in result.proposals)
    print(f"\n  -- R3, the LLM rung ({provider}) --")
    print(f"  credits offered     {len(result.proposals):>9}   after R0-R2 and minus any "
          f"credit R2 refused as E14")
    print(f"  proposals accepted  {len(accepted):>9}   validated to the paisa")
    print(f"  proposals rejected  {len(result.rejected):>9}   by the validator, at any "
          f"stated confidence")
    print(f"  tokens              {prompt_tokens + completion_tokens:>9}   "
          f"{prompt_tokens} in / {completion_tokens} out")
    print(f"  model cost                  ₹0   free tier; cost at any rate is the tokens "
          f"above times that rate")
    if not result.proposals:
        return
    matched_conf = [p.confidence for p in result.proposals if p.code == "MATCH"]
    other_conf = [p.confidence for p in result.proposals if p.code != "MATCH"]
    print(f"  stated confidence   {min(p.confidence for p in result.proposals)}-"
          f"{max(p.confidence for p in result.proposals)}   "
          f"{len(matched_conf)} match proposals, {len(other_conf)} refusals")
    print(f"                                  no threshold is applied -- the validator is "
          f"exact, so confidence cannot change a decision")


def evaluate(name: str, provider: str = "") -> dict:
    ledger = load(ROOT.joinpath("data", name))
    truth = json.loads(
        ROOT.joinpath("eval", "ground_truth", f"{name}.json").read_text(encoding="utf-8"))

    proposer = None
    if provider:
        from functools import partial
        from propose import propose
        proposer = partial(propose, provider=provider)

    started = time.monotonic_ns()
    result = run(ledger, through="R3" if provider else "R2", propose=proposer)
    run_ms = (time.monotonic_ns() - started) // 1000000

    residue = check_conservation(ledger, truth)
    check_partition(ledger, result)
    metrics = score(ledger, result, truth, run_ms, residue)
    metrics["exceptions"] = score_exceptions(ledger, result, truth)
    metrics["coverage_split"] = coverage_split(ledger, result, classify(ledger, result)[0])
    metrics["fees"] = fee_totals(audit_fees(ledger))
    metrics["refund_fee_burden"] = refund_fee_burden(ledger)
    if provider:
        metrics["rungs"] = R3_RUNGS
        metrics["provider"] = provider
        metrics["prompt_tokens"] = sum(p.prompt_tokens for p in result.proposals)
        metrics["completion_tokens"] = sum(p.completion_tokens for p in result.proposals)
        metrics["proposals"] = len(result.proposals)
        metrics["proposals_accepted"] = len([m for m in result.matches if m.rung == "R3"])
        metrics["proposals_rejected"] = len(result.rejected)
        metrics["confidences"] = [
            {"bank_ref": p.bank_ref, "code": p.code, "confidence": p.confidence,
             "accepted": any(m.bank_ref == p.bank_ref and m.rung == "R3"
                             for m in result.matches)}
            for p in result.proposals]
    metrics["_result"] = result
    return metrics


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
    args = sys.argv[1:] or ["train"]
    provider = ""
    if "--r3" in args:
        at = args.index("--r3")
        provider = args[at + 1]
        args = args[:at] + args[at + 2:]
    names = args or ["train"]
    for name in names:
        try:
            metrics = evaluate(name, provider)
        except IngestError as bad:
            print(f"{len(bad.problems)} rows could not be read. Nothing was loaded.\n")
            for problem in bad.problems:
                print(f"  {problem}")
            sys.exit(1)
        report(name, metrics)
        report_coverage_split(metrics["coverage_split"])
        report_exceptions(metrics["exceptions"])
        report_fees(metrics["fees"], metrics["refund_fee_burden"])
        if provider:
            report_r3(metrics.pop("_result"), provider)
        metrics.pop("_result", None)
        print(f"\n  written to {write_results(name, metrics).relative_to(ROOT)}\n")

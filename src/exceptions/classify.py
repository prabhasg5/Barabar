"""The exception taxonomy, applied. PRD 6: fourteen codes, every one of them scored.

Two sources, and the split is principled rather than incidental:

  * **The ladder's `Result`** carries facts about the *matching attempt* that are invisible
    in the ledger once it has finished. A match that consumed tolerance (E03) is
    indistinguishable from a clean one by the time you are looking at CSVs, and the set of
    subsets that tied to an ambiguous credit (E14) is gone entirely. Only the ladder knows.
  * **The ledger** carries facts about the *records* -- a payment with no order, a settlement
    with no credit -- which need no matching at all.

A code that only one source can see must be raised by that source, or the path does not
exist and reports as a clean zero. That is how E03 would have been lost: a classifier that
walks unmatched records alone never reaches a match that succeeded.

**Where evidence runs out, no code is assigned.** An unclassified row is honest; a wrong code
is a false break, and a false break costs a controller the same investigation a real one does.
`classify` returns the unclassified records alongside the exceptions and the caller reports
the count -- it is a headline number, not a footnote.

No floats: this module is under src/ and the no-float scan covers it.
"""

from dataclasses import dataclass
from datetime import date

from audit.fees import audit_fees
from ingest.load import Ledger
from match.ladder import R1_WINDOW_DAYS, Result, TOLERANCE_PAISE
from money import Paise, format_rupees

# The aggregator whose settlements these are. A bank credit that does not name it is not a
# settlement narration at all -- which is what separates an unreadable string (E13, the money
# is fine) from money that arrived from somewhere else entirely (E01).
#
# This is domain knowledge, not a constant shared with the generator: a reconciler is always
# run against a named payment processor, and "the narration does not mention the payer" is how
# a human tells a settlement credit from an unrelated one. It is deliberately not the
# generator's list of garbage strings -- matching on those would be fitting to the fixture.
AGGREGATOR = "RAZORPAY"

# E10's two payments are identical by construction, so nothing in the ledger says which of
# them is the duplicate. The exception names both and lets a human decide; see `_duplicates`.
DUPLICATE_KEYS = ("order_id", "amount_paise")


@dataclass(frozen=True)
class Exception_:
    """One row of the exception report. PRD 6: code, both record ids, delta, rung, reason."""

    code: str
    record_type: str
    record_id: str
    other_id: str            # the record on the far side, or "" where there is none
    delta_paise: Paise
    rung: str                # the rung that gave up, or "-" for records no rung examines
    reason: str

    @property
    def is_break(self) -> bool:
        """PRD 6. E14 is the only code that is not a break -- nothing is wrong with the money."""
        return self.code != "E14"


def _period_end(ledger: Ledger) -> date:
    """The last day the bank statement covers.

    A settlement dated after this cannot have been credited in the statement we hold, so it
    is in transit rather than missing. This retires the `in_transit_paise` borrow flagged at
    step 5: the boundary is derived from the bank statement itself rather than read out of
    the answer key, which is what makes the figure one the engine could produce on a real
    merchant's files. Verified against the answer key on both seeds -- see DECISIONS.md.
    """
    return max(row["txn_date"] for row in ledger.bank)


def _unreadable(narration: str) -> bool:
    return AGGREGATOR not in narration.upper()


def _duplicates(ledger: Ledger) -> list[list[dict]]:
    """Payments identical in order and amount. Two captures of one order is E10.

    Returns groups, not winners. The generator knows which row it added; the ledger does not,
    and picking the later id would be a guess dressed as an answer -- both rows are the same
    payment twice. The exception names the whole group.
    """
    groups: dict[tuple, list[dict]] = {}
    for p in ledger.payments:
        if p["order_id"]:
            groups.setdefault(tuple(p[k] for k in DUPLICATE_KEYS), []).append(p)
    return [g for g in groups.values() if len(g) > 1]


def _orphan_explains(ledger: Ledger) -> dict[int, int]:
    """How many orphaned payments carry each amount.

    An order whose status says paid but has no payment row is either a ghost (E07) or the
    other half of an orphaned payment (E06) -- unlinking a payment leaves its order looking
    unpaid. The two are the same shape in the ledger. An orphan of exactly the order's gross
    is evidence they are one transaction, so the order is not reported as E07.

    It costs recall: an amount collision hides a real E07, measured at 1 of 16 on held-out
    and 0 of 16 on train *(train+heldout, 6b, 2026-09-01)*. It buys precision on 15 orders
    per seed that are not ghosts at all. Precision beats recall -- PRD 5.
    """
    counts: dict[int, int] = {}
    for p in ledger.payments:
        if not p["order_id"]:
            counts[p["amount_paise"]] = counts.get(p["amount_paise"], 0) + 1
    return counts


def _nearest_open(ledger: Ledger, result: Result, row: dict) -> tuple[str, list[str]]:
    """The open settlement an unmatched-but-readable credit most likely belongs to.

    A credit whose amount drifted outside tolerance (E04) leaves its settlement open too, and
    that settlement looks exactly like one whose credit never arrived (E02) -- both are
    "settled, not matched". The difference is that the E04's money did arrive, at the wrong
    figure, so calling it E02 as well reports one problem twice and overstates missing money.

    Paired on date, not on amount: the amount is the thing that is wrong, so it cannot also be
    the evidence. Only a settlement inside R1's window whose net is *outside* tolerance is
    eligible -- inside tolerance the ladder would already have matched it. Returns "" where no
    single candidate stands out, and then both records are reported separately, which is the
    honest outcome rather than a guessed pair.

    Returns `(paired_id, ambiguous_ids)`. **The ambiguous branch does not fire on either seed**
    -- it is reported as zero rather than claimed to work; see DECISIONS.md, 2026-09-01.
    """
    near = [s for s in ledger.settlements
            if s["settlement_id"] in set(result.unmatched_settlements)
            and abs((s["settled_at"] - row["txn_date"]).days) <= R1_WINDOW_DAYS
            and abs(s["net_amount_paise"] - row["credit_paise"]) > TOLERANCE_PAISE]
    if len(near) == 1:
        return near[0]["settlement_id"], []
    # More than one open settlement could be this credit's, and nothing available
    # discriminates. Rather than pick, hand them back unclassified: calling one of them E02
    # would assert money never arrived when it may have arrived at the wrong figure.
    return "", [s["settlement_id"] for s in near]


def classify(ledger: Ledger, result: Result) -> tuple[list[Exception_], list[tuple[str, str]]]:
    """Every exception the ledger and the match result together support.

    Returns `(exceptions, unclassified)`, where `unclassified` is (record_type, record_id)
    for records that reached no rule. E05 is not raised here -- the fee audit is step 8 and
    owns it -- and E11 cannot be raised at all; both are stated in `known_gaps()` rather
    than left as empty columns.
    """
    out: list[Exception_] = []
    unclassified: list[tuple[str, str]] = []
    drifted: set[str] = set()
    period_end = _period_end(ledger)
    matched_refs = {m.bank_ref for m in result.matches}
    ambiguous_refs = {a.bank_ref for a in result.ambiguous}

    # --- from the ladder: facts about the matching attempt, gone from the ledger afterwards --
    for a in result.ambiguous:
        shown = " or ".join("+".join(c) for c in a.candidates)
        out.append(Exception_(
            "E14", "bank", a.bank_ref, "", Paise(0), "R2",
            f"{len(a.candidates)} combinations of settlements tie to this credit exactly "
            f"({shown}) and the narration names none of them. Nothing is wrong with the "
            f"money -- one question settles it."))

    for m in result.flagged:
        out.append(Exception_(
            "E03", "bank", m.bank_ref, m.settlement_ids[0], m.delta_paise, m.rung,
            f"Matched, but the credit is {format_rupees(Paise(abs(int(m.delta_paise))))} "
            f"off the settled net -- inside the "
            f"{format_rupees(Paise(TOLERANCE_PAISE))} tolerance, so the match stands and "
            f"the drift is counted."))

    # --- from the ledger: the bank side ---
    for row in ledger.bank:
        ref, narration = row["bank_ref"], row["narration"]
        if not row["credit_paise"] or ref in ambiguous_refs:
            continue
        if _unreadable(narration):
            if ref in matched_refs:
                out.append(Exception_(
                    "E13", "bank", ref, "", Paise(0), "-",
                    f"Matched on amount and date, but the narration does not name "
                    f"{AGGREGATOR.title()} and cannot be read: {narration!r}. The money is "
                    f"fine; the description is not."))
            else:
                out.append(Exception_(
                    "E01", "bank", ref, "", Paise(row["credit_paise"]), "R2",
                    f"{format_rupees(Paise(row['credit_paise']))} arrived and nothing "
                    f"explains it -- no settlement ties to it and the narration does not "
                    f"name {AGGREGATOR.title()}."))
        elif ref not in matched_refs:
            near, tied = _nearest_open(ledger, result, row)
            drifted.update({near} if near else set())
            unclassified.extend(("settlement", sid) for sid in tied)
            out.append(Exception_(
                "E04", "bank", ref, near or "", Paise(row["credit_paise"]), "R2",
                f"Reads as a settlement credit but no settlement or combination ties to "
                f"{format_rupees(Paise(row['credit_paise']))} within tolerance."
                + (f" The closest open settlement, {near}, is off by more than tolerance."
                   if near else "")))

    # --- from the ledger: the settlement side. The only thing separating E02 from E12 is the
    # period boundary, which is why _period_end had to stop being borrowed. ---
    spoken_for = {sid for a in result.ambiguous for c in a.candidates for sid in c}
    for sid in result.unmatched_settlements:
        s = next(x for x in ledger.settlements if x["settlement_id"] == sid)
        # The period test comes first and is unconditional. Whether a settlement is in
        # transit is a fact about its date, not about how the match went, so nothing the
        # ladder did may suppress it -- an in-transit settlement can also sit inside an E14's
        # candidate subset, and skipping it there loses a real E12 for a matching reason.
        if s["settled_at"] > period_end:
            out.append(Exception_(
                "E12", "settlement", sid, "", Paise(0), "-",
                f"Settled {s['settled_at']:%d %b}, after the statement ends "
                f"{period_end:%d %b}. In transit, not missing -- it lands next period."))
        elif sid in {u[1] for u in unclassified}:
            continue          # evidence ran out on which credit it belongs to; already
                              # counted as unclassified rather than asserted as missing.
        elif sid in spoken_for or sid in drifted:
            continue          # already named by the E14 or E04 row on the other side of it.
                              # Its credit exists; reporting it again as a settlement that
                              # never arrived counts one problem twice and invents a break.
        else:
            out.append(Exception_(
                "E02", "settlement", sid, "", Paise(-s["net_amount_paise"]), "R2",
                f"{format_rupees(Paise(s['net_amount_paise']))} settled on "
                f"{s['settled_at']:%d %b} and never reached the bank."))

    # --- from the ledger: linkage. No money moves; the trail is cut. ---
    for p in ledger.payments:
        if not p["order_id"]:
            out.append(Exception_(
                "E06", "payment", p["payment_id"], "", Paise(0), "-",
                "Payment captured against no order -- the money is real, the trail is cut."))

    orphan_amounts = _orphan_explains(ledger)
    paid_with_payment = {p["order_id"] for p in ledger.payments if p["order_id"]}
    for o in ledger.orders:
        if o["status"] == "paid" and o["order_id"] not in paid_with_payment:
            if orphan_amounts.get(o["gross_amount_paise"]):
                continue          # an orphaned payment of this amount explains it -- E06, not E07
            out.append(Exception_(
                "E07", "order", o["order_id"], "", Paise(0), "-",
                f"Order says paid, but no payment exists for it and no orphaned payment "
                f"carries its {format_rupees(Paise(o['gross_amount_paise']))}."))

    for r in ledger.refunds:
        if r["payment_id"]:
            continue
        code, what = ("E09", "Chargeback") if r["type"] == "chargeback" else ("E08", "Refund")
        out.append(Exception_(
            code, "refund", r["refund_id"], "", Paise(0), "-",
            f"{what} of {format_rupees(Paise(r['amount_paise']))} is linked to no original "
            f"payment."))

    for v in audit_fees(ledger):
        out.append(Exception_(
            "E05", "payment", v.payment_id, "", v.delta_paise, "-",
            f"{v.method.title()} payment of {format_rupees(v.amount_paise)} was billed "
            f"{format_rupees(v.actual_paise)} in fee and GST against a contracted "
            f"{format_rupees(v.expected_paise)} -- "
            f"{'over' if v.overcharged else 'under'}charged by "
            f"{format_rupees(Paise(abs(int(v.delta_paise))))}."))

    for group in _duplicates(ledger):
        ids = sorted(p["payment_id"] for p in group)
        out.append(Exception_(
            "E10", "payment", ids[0], ids[1], Paise(group[0]["amount_paise"]),
            "-", f"{len(ids)} payments of "
            f"{format_rupees(Paise(group[0]['amount_paise']))} against order "
            f"{group[0]['order_id']}. One is a duplicate capture; the ledger does not say "
            f"which, so both are named."))

    return out, unclassified


def known_gaps() -> dict[str, str]:
    """Codes in PRD 6's table that `classify` deliberately does not raise, and why.

    Stated rather than left as empty columns in the confusion matrix. A code with no rows
    looks the same whether it never occurred, was never detectable, or was never implemented,
    and those are three different facts.
    """
    return {
        "E11": "Not detectable from the CSVs. A partial refund reduces the refund row and "
               "the settlement's refund total by the same figure, so both sides stay "
               "consistent and no ledger field records what the refund was originally "
               "raised for. Detecting it needs a field the merchant's export does not "
               "carry -- see DECISIONS.md, 2026-09-01.",
    }

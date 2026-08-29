"""The matching ladder: rungs R0 and R1. Cheap and certain before clever.

A match is one bank credit tied to the settlement batches inside it, and through them
to the payments inside those. That whole triple is the unit -- four of five payments
right is one false match, not four right ones.

Two rules govern every rung here and the two still to come:

  * Precision over recall. A credit with two plausible settlements gets no match at all.
    A false match hides a real break, and someone signs off on wrong books.
  * Tolerance is never silent. A match that lands within 100 paise is still a match, but
    it is flagged and its drift is counted into the run total.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ingest.load import Ledger
from money import Paise, format_rupees

TOLERANCE_PAISE = 100        # PRD 5: absolute, per whole match, never a percentage
DATE_WINDOW_DAYS = 2         # a credit lands the day its batch settles, give or take


@dataclass(frozen=True)
class Match:
    bank_ref: str
    settlement_ids: tuple[str, ...]
    payment_ids: tuple[str, ...]
    rung: str
    delta_paise: Paise       # credit minus settled net; non-zero means tolerance was spent


@dataclass
class Result:
    matches: list[Match] = field(default_factory=list)
    unmatched_credits: list[str] = field(default_factory=list)
    unmatched_settlements: list[str] = field(default_factory=list)
    trail: dict[str, list[str]] = field(default_factory=dict)

    @property
    def drift_paise(self) -> Paise:
        """Total tolerance absorbed this run. Half a rupee four thousand times is 2,000."""
        return Paise(sum(abs(m.delta_paise) for m in self.matches))

    @property
    def flagged(self) -> list[Match]:
        """Matches that consumed tolerance -- E03 candidates for the classifier."""
        return [m for m in self.matches if m.delta_paise]

    def by_rung(self) -> dict[str, int]:
        counts = {"R0": 0, "R1": 0}
        for m in self.matches:
            counts[m.rung] = counts.get(m.rung, 0) + 1
        return counts


@dataclass
class Index:
    """Built once from the ledger. Every rung reads it; no rung reads the CSVs again."""
    settlements: list[dict]
    by_utr: dict[str, dict]
    payments_of: dict[str, list[str]]
    claimed: set[str] = field(default_factory=set)
    disputed: set[str] = field(default_factory=set)

    def open_settlements(self) -> list[dict]:
        """Claimed is taken; disputed is ambiguous evidence and stays out of every rung.

        Two credits naming one settlement does not become unambiguous further down the
        ladder -- without this, R1 hands a later rung's guess the batch R0 refused.
        """
        out = self.claimed | self.disputed
        return [s for s in self.settlements if s["settlement_id"] not in out]

    def unclaimed(self) -> list[dict]:
        return [s for s in self.settlements if s["settlement_id"] not in self.claimed]


def index(ledger: Ledger) -> Index:
    payments_of: dict[str, list[str]] = {}
    for p in ledger.payments:
        if p["settlement_id"]:
            payments_of.setdefault(p["settlement_id"], []).append(p["payment_id"])
    return Index(
        settlements=list(ledger.settlements),
        by_utr={s["utr"]: s for s in ledger.settlements if s["utr"]},
        payments_of=payments_of,
    )


def _tokens(narration: str) -> list[str]:
    """Reference-shaped tokens out of a machine narration.

    Bank narration is unreliable by nature, so this pulls candidates rather than parsing:
    any run of alphanumerics at least five long that is more than half digits. A verbatim
    UTR, a truncated one and a garbled one all survive; RAZORPAY and XXXXX do not.
    """
    parts = re.split(r"[^0-9A-Za-z]+", narration)
    return [t for t in parts if len(t) >= 5 and sum(c.isdigit() for c in t) * 2 > len(t)]


def _resembles(token: str, utr: str) -> bool:
    """A truncated or garbled UTR: a prefix of the real one, or one character off it."""
    if len(token) >= 5 and utr.startswith(token):
        return True
    return len(token) == len(utr) and sum(a != b for a, b in zip(token, utr)) == 1


def _within(credit: dict, settled: date) -> bool:
    return abs(credit["txn_date"] - settled) <= timedelta(days=DATE_WINDOW_DAYS)


def _claim(idx: Index, result: Result, credit: dict, settlement: dict,
           rung: str, delta: int) -> None:
    sid = settlement["settlement_id"]
    idx.claimed.add(sid)
    result.matches.append(Match(
        bank_ref=credit["bank_ref"],
        settlement_ids=(sid,),
        payment_ids=tuple(idx.payments_of.get(sid, [])),
        rung=rung,
        delta_paise=Paise(delta),
    ))


def r0(ledger: Ledger, idx: Index, result: Result) -> list[dict]:
    """Exact: a UTR from the narration names a settlement, and the amount ties.

    Returns the credits it did not claim. A bundled credit carries only the first
    batch's UTR, so it fails the amount test here by design -- that is R2's reason
    to exist, not a miss.
    """
    proposals: dict[str, list[tuple[dict, dict, int]]] = {}
    rejected: set[str] = set()

    for credit in ledger.bank:
        note = result.trail.setdefault(credit["bank_ref"], [])
        hits = [idx.by_utr[t] for t in _tokens(credit["narration"]) if t in idx.by_utr]
        if not hits:
            note.append("R0: no UTR in the narration matched a settlement.")
            rejected.add(credit["bank_ref"])
            continue
        ties = [(s, credit["credit_paise"] - s["net_amount_paise"]) for s in hits]
        near = [(s, d) for s, d in ties if abs(d) <= TOLERANCE_PAISE]
        if len(near) != 1:
            for s, d in ties:
                note.append(
                    f"R0: UTR {s['utr']} names settlement {s['settlement_id']}, but the "
                    f"credit is {format_rupees(Paise(abs(d)))} "
                    f"{'over' if d > 0 else 'short'} of it -- outside tolerance."
                    if abs(d) > TOLERANCE_PAISE else
                    f"R0: UTR {s['utr']} also ties within tolerance -- ambiguous, no match."
                )
            rejected.add(credit["bank_ref"])
            continue
        settlement, delta = near[0]
        proposals.setdefault(settlement["settlement_id"], []).append((credit, settlement, delta))

    contested = {sid for sid, props in proposals.items() if len(props) > 1}
    for sid, props in proposals.items():
        for credit, settlement, delta in props:
            note = result.trail[credit["bank_ref"]]
            if sid in contested:
                idx.disputed.add(sid)
                note.append(f"R0: settlement {sid} is claimed by "
                            f"{len(props)} credits -- no match, precision over recall.")
                rejected.add(credit["bank_ref"])
                continue
            _claim(idx, result, credit, settlement, "R0", delta)
            note.append(
                f"R0: UTR {settlement['utr']} found in the narration and the amount ties "
                f"to the paisa." if delta == 0 else
                f"R0: UTR {settlement['utr']} found in the narration; amount is "
                f"{format_rupees(Paise(abs(delta)))} off, inside tolerance -- matched "
                f"and flagged."
            )
    return [c for c in ledger.bank if c["bank_ref"] in rejected]


def r1(credits: list[dict], idx: Index, result: Result) -> list[dict]:
    """Composite: amount within tolerance, a date window, and a partial reference.

    Runs only on what R0 left. A credit with more than one surviving candidate gets
    no match -- the same uniqueness guard R2 will need for subset sums.
    """
    rest = []
    for credit in credits:
        note = result.trail[credit["bank_ref"]]
        near = [
            (s, credit["credit_paise"] - s["net_amount_paise"])
            for s in idx.open_settlements()
            if abs(credit["credit_paise"] - s["net_amount_paise"]) <= TOLERANCE_PAISE
            and _within(credit, s["settled_at"])
        ]
        tokens = _tokens(credit["narration"])
        partial = [(s, d) for s, d in near
                   if any(_resembles(t, s["utr"]) for t in tokens)]
        candidates = partial or near

        if not candidates:
            note.append("R1: no settlement is within a rupee and two days of this credit.")
            rest.append(credit)
            continue
        if len(candidates) > 1:
            note.append(f"R1: {len(candidates)} settlements fit the amount and the date "
                        f"window -- no match, precision over recall.")
            rest.append(credit)
            continue

        settlement, delta = candidates[0]
        _claim(idx, result, credit, settlement, "R1", delta)
        why = ("a partial reference in the narration" if partial
               else "the amount and settlement date")
        note.append(
            f"R1: settlement {settlement['settlement_id']} matched on {why}"
            + (", ties to the paisa." if delta == 0 else
               f"; amount is {format_rupees(Paise(abs(delta)))} off, inside tolerance "
               f"-- matched and flagged.")
        )
    return rest


def run(ledger: Ledger) -> Result:
    """Walk the ladder. Deterministic: same ledger in, same result out."""
    idx = index(ledger)
    result = Result()
    left = r1(r0(ledger, idx, result), idx, result)
    result.unmatched_credits = [c["bank_ref"] for c in left]
    result.unmatched_settlements = [s["settlement_id"] for s in idx.unclaimed()]
    return result

"""The matching ladder: rungs R0, R1 and R2. Cheap and certain before clever.

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
from itertools import combinations
from datetime import date, timedelta

from ingest.load import Ledger
from money import Paise, format_rupees

TOLERANCE_PAISE = 100        # PRD 5: absolute, per whole match, never a percentage

# Window and tolerance are per-rung, not module-level (PRD 5). R2 has combinatorially more
# chances to land on a plausible sum than a rung matching one settlement, so it gets its own
# and stricter values, and no R2 code path can reach TOLERANCE_PAISE by accident.
R1_WINDOW_DAYS = 2           # a credit lands the day its batch settles, give or take
# A size-N bundle spans N-1 settlement gaps, and settlements land on business days, so one
# weekend inside those gaps adds two calendar days: a size-5 bundle reaches 6 days from its
# credit and no further. Measured max is exactly 6 (train tops out at 5 because its largest
# bundle is size 4 -- the same train-fitted reasoning that put subset size at 2-4).
R2_WINDOW_DAYS = 6
R2_TOLERANCE_PAISE = 0       # R2 spends none. Exact, or it is an exception.
R2_SIZE_MIN, R2_SIZE_MAX = 2, 5


@dataclass(frozen=True)
class Match:
    bank_ref: str
    settlement_ids: tuple[str, ...]
    payment_ids: tuple[str, ...]
    rung: str
    delta_paise: Paise       # credit minus settled net; non-zero means tolerance was spent


@dataclass(frozen=True)
class Ambiguity:
    """E14. Two or more subsets tie exactly to one credit and nothing chooses between them.

    Not a break -- PRD 6 gives it `is_break: false`. Nothing is wrong with the money; the
    evidence does not single out one answer. Carries every candidate, not a count, because
    the exception is only actionable if the reviewer can see what the choices were.
    """
    bank_ref: str
    candidates: tuple[tuple[str, ...], ...]


@dataclass
class Result:
    matches: list[Match] = field(default_factory=list)
    unmatched_credits: list[str] = field(default_factory=list)
    unmatched_settlements: list[str] = field(default_factory=list)
    ambiguous: list[Ambiguity] = field(default_factory=list)
    trail: dict[str, list[str]] = field(default_factory=dict)
    # Every proposal R3 made, and the subset the validator refused. Kept rather than dropped:
    # "the model proposed and deterministic code said no" is the evidence for the safety rule.
    proposals: list = field(default_factory=list)
    rejected: list = field(default_factory=list)

    @property
    def drift_paise(self) -> Paise:
        """Total tolerance absorbed this run. Half a rupee four thousand times is 2,000."""
        return Paise(sum(abs(m.delta_paise) for m in self.matches))

    @property
    def flagged(self) -> list[Match]:
        """Matches that consumed tolerance -- E03 candidates for the classifier."""
        return [m for m in self.matches if m.delta_paise]

    def by_rung(self) -> dict[str, int]:
        counts = {"R0": 0, "R1": 0, "R2": 0, "R3": 0}
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


def _within(credit: dict, settled: date, days: int) -> bool:
    return abs(credit["txn_date"] - settled) <= timedelta(days=days)


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


def _claim_many(idx: Index, result: Result, credit: dict, subset: tuple[dict, ...],
                rung: str) -> None:
    """Claim 2-5 settlements as one match, or not at all.

    `payment_ids` come from the payments' own `settlement_id`, which is what the answer key
    counts: a duplicate payment (E10) carries its original's settlement and belongs inside
    the match. Deriving the set any other way -- through orders, say -- would drop it and
    score the whole bundle false with every settlement correct.
    """
    sids = tuple(s["settlement_id"] for s in subset)
    idx.claimed.update(sids)
    result.matches.append(Match(
        bank_ref=credit["bank_ref"],
        settlement_ids=sids,
        payment_ids=tuple(pid for sid in sids for pid in idx.payments_of.get(sid, [])),
        rung=rung,
        delta_paise=Paise(0),        # exact by construction; R2 spends no tolerance
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
            and _within(credit, s["settled_at"], R1_WINDOW_DAYS)
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


def _pool(credit: dict, idx: Index) -> list[dict]:
    """Bound the candidate pool before solving it. PRD 5: ambiguity is a filter problem.

    Two filters, both from the credit itself: settlements within R2's date window, and none
    whose net alone already exceeds the credit. The filter, not the solver, is what removes
    ambiguity: unfiltered, 2 of 8 train bundles and 1 of 6 held-out admit more than one exact
    subset; with the window on, 1 and 1, and the survivor on each seed is the engineered
    decoy. Same solver, same tolerance, only the size of the pool changed.

    Those counts are pinned to the current data. The window's *value* is not measured at all
    -- it is derived in PRD 5 and lives in R2_WINDOW_DAYS above. Do not restate it here.
    """
    return [
        s for s in idx.open_settlements()
        if _within(credit, s["settled_at"], R2_WINDOW_DAYS)
        and s["net_amount_paise"] <= credit["credit_paise"]
    ]


def _exact_subsets(pool: list[dict], target: int) -> list[tuple[dict, ...]]:
    """Every subset of 2-5 settlements whose nets sum to `target` exactly.

    Brute force over the bounded pool, which runs 2-8 settlements after `_pool` -- at most
    a few hundred combinations. The bound is what makes this cheap; meet-in-the-middle is
    the upgrade if a merchant settling several times a day ever puts hundreds in one window.

    PRD 5 says to count solutions and stop at two. The decision here is identical -- two is
    a refusal whatever the third would have been -- but the enumeration runs to the end
    because PRD 6 requires E14 to carry every candidate, and on a pool this size that costs
    nothing.
    """
    return [c for size in range(R2_SIZE_MIN, R2_SIZE_MAX + 1)
            for c in combinations(pool, size)
            if abs(sum(s["net_amount_paise"] for s in c) - target) <= R2_TOLERANCE_PAISE]


def _witnessed(credit: dict, subsets: list[tuple[dict, ...]]) -> list[tuple[dict, ...]]:
    """The subsets a partial UTR in the narration actually points at.

    The one discriminator PRD 5 permits, and only as evidence: a reference in the narration
    naming a settlement inside one subset and not the other. Everything else it explicitly
    forbids -- fewer settlements, earlier dates, fewer orphans left behind -- because those
    are guesses in the costume of logic, and each buys a recall point that was never earned.
    """
    tokens = _tokens(credit["narration"])
    return [sub for sub in subsets
            if any(t == s["utr"] or _resembles(t, s["utr"])
                   for s in sub for t in tokens)]


def r2(credits: list[dict], idx: Index, result: Result) -> list[dict]:
    """Combination: which subset of settlements sums to this credit, exactly.

    Runs on what R0 and R1 left. Exact or nothing -- a bundle that ties only within
    tolerance is an exception, not a match, because every paisa of slack is a window that
    any of a few hundred subsets can fall into.

    Proposes first and claims second, the same two passes R0 uses. Claiming as it went would
    let the first credit take a subset the second one needed, and the second would then fail
    for a reason that is an artefact of iteration order.
    """
    proposals: dict[str, tuple[dict, tuple[dict, ...]]] = {}
    rest: list[dict] = []

    for credit in credits:
        note = result.trail[credit["bank_ref"]]
        pool = _pool(credit, idx)
        if len(pool) < R2_SIZE_MIN:
            note.append(f"R2: only {len(pool)} settlements sit within "
                        f"{R2_WINDOW_DAYS} days of this credit -- nothing to combine.")
            rest.append(credit)
            continue

        ties = _exact_subsets(pool, credit["credit_paise"])
        if not ties:
            note.append(f"R2: no combination of {len(pool)} settlements in the window sums "
                        f"to this credit exactly.")
            rest.append(credit)
            continue

        if len(ties) > 1:
            chosen = _witnessed(credit, ties)
            if len(chosen) != 1:
                result.ambiguous.append(Ambiguity(
                    bank_ref=credit["bank_ref"],
                    candidates=tuple(tuple(s["settlement_id"] for s in sub) for sub in ties),
                ))
                note.append(
                    f"R2: {len(ties)} different combinations tie to this credit exactly and "
                    f"the narration does not single one out -- E14, no match. Picking one "
                    f"would be a guess."
                )
                rest.append(credit)
                continue
            note.append(f"R2: {len(ties)} combinations tie exactly; a reference in the "
                        f"narration names a settlement in only one of them.")
            ties = chosen

        proposals.setdefault(credit["bank_ref"], (credit, ties[0]))

    taken: dict[str, list[str]] = {}
    for ref, (_, subset) in proposals.items():
        for s in subset:
            taken.setdefault(s["settlement_id"], []).append(ref)
    contested = {sid for sid, refs in taken.items() if len(refs) > 1}

    for ref, (credit, subset) in proposals.items():
        note = result.trail[ref]
        clash = [s["settlement_id"] for s in subset if s["settlement_id"] in contested]
        if clash:
            for sid in clash:
                idx.disputed.add(sid)
            note.append(f"R2: settlement {clash[0]} is inside the winning combination for "
                        f"more than one credit -- no match, precision over recall.")
            rest.append(credit)
            continue
        _claim_many(idx, result, credit, subset, "R2")
        note.append(f"R2: {len(subset)} settlements sum to this credit to the paisa, and "
                    f"no other combination in the window does.")
    return rest


def r3(credits: list[dict], idx: Index, result: Result, propose) -> list[dict]:
    """The LLM rung. **The model proposes; this function disposes.**

    `propose(credit, candidates) -> Proposal` is injected so the ladder never imports a
    provider and the test suite can pass a hand-built proposal in. Everything the model
    returns is a *candidate*: it names settlement ids, and the arithmetic is done here.

    **There is no confidence threshold, and that is deliberate.** The check below is binary and
    exact -- the named settlements sum to the credit to the paisa, or they do not. A proposal
    that ties is correct at a stated confidence of 5; one that does not is wrong at 99. A
    threshold could only discard proposals *before* validating them, and validating costs a
    subtraction. Confidence is recorded so the run can report whether it tracks being right,
    which is a measurement rather than a control.

    Proposals that do not tie are kept on `result.rejected` rather than dropped, because "the
    model proposed and the validator refused" is the evidence for the safety rule and PRD 12
    wants it in the trail.
    """
    rest: list[dict] = []
    refused = {a.bank_ref for a in result.ambiguous}
    for credit in credits:
        note = result.trail[credit["bank_ref"]]
        # A credit R2 raised E14 on is never offered to the model. PRD 6 defines E14 as the
        # evidence failing to single out an answer, and PRD 8 scores a claim on one as a false
        # match *even when it equals the true subset* -- guessing correctly is not knowing.
        #
        # This is not belt-and-braces over the uniqueness check below; it is the guard that
        # actually holds. By the time R3 runs, R2 has claimed the rival subset's members
        # against their own bundled credits, so only one subset is still open and re-running
        # the enumeration here finds a single tie. The ambiguity is real but has dissolved a
        # rung later -- the same "a rival must survive the ladder" effect as the decoys, one
        # rung further on. Uniqueness at R3 time therefore cannot see it, and only R2's
        # refusal can.
        if credit["bank_ref"] in refused:
            note.append("R3: not offered to the model -- R2 raised E14 on this credit and a "
                        "refusal is the answer. Picking one arm would be a guess.")
            rest.append(credit)
            continue
        candidates = [s for s in idx.open_settlements()
                      if _within(credit, s["settled_at"], R2_WINDOW_DAYS)]
        proposal = propose(credit, candidates)
        result.proposals.append(proposal)

        if proposal.code != "MATCH" or not proposal.settlement_ids:
            note.append(f"R3: the model returned {proposal.code} and proposed no match "
                        f"(confidence {proposal.confidence}).")
            rest.append(credit)
            continue

        named = [s for s in candidates if s["settlement_id"] in set(proposal.settlement_ids)]
        total = sum(s["net_amount_paise"] for s in named)
        missing = set(proposal.settlement_ids) - {s["settlement_id"] for s in named}
        # Tying is necessary and NOT sufficient. R2 refuses a credit that two subsets tie to,
        # and a proposal that ties is not evidence the model found the only one -- on the
        # first live run the model proposed one arm of a known E14 at confidence 100 and an
        # earlier version of this validator accepted it, walking straight around acceptance
        # criterion 8. Uniqueness is re-checked here, by the same enumeration R2 uses, so no
        # rung can claim an ambiguous credit however it arrived at the answer.
        ties = _exact_subsets(candidates, credit["credit_paise"]) if named else []
        if missing or total != credit["credit_paise"] or len(ties) > 1:
            result.rejected.append(proposal)
            why = (f"named {len(missing)} settlement(s) that are not open"
                   if missing else
                   f"the named settlements sum to {total}, not {credit['credit_paise']}"
                   if total != credit["credit_paise"] else
                   f"{len(ties)} different subsets tie to this credit exactly, so no proposal "
                   f"can be evidence for one of them -- E14 stands")
            note.append(f"R3: the model proposed a match at confidence "
                        f"{proposal.confidence} and the validator rejected it -- {why}. "
                        f"Confidence does not enter this decision.")
            rest.append(credit)
            continue

        result.matches.append(Match(
            bank_ref=credit["bank_ref"],
            settlement_ids=tuple(sorted(s["settlement_id"] for s in named)),
            payment_ids=tuple(sorted(pid for s in named
                                     for pid in idx.payments_of.get(s["settlement_id"], []))),
            rung="R3", delta_paise=Paise(0)))
        for s in named:
            idx.claimed.add(s["settlement_id"])
        note.append(f"R3: the model proposed these settlements and the validator confirmed "
                    f"they tie to the paisa.")
    return rest


def run(ledger: Ledger, through: str = "R2", propose=None) -> Result:
    """Walk the ladder. Deterministic: same ledger in, same result out.

    `through` stops early, which is how the before/after numbers acceptance criterion 10
    wants are reproduced from the same code rather than from a remembered figure. R3 runs only
    when a proposer is supplied, so the deterministic rungs never depend on a model being
    reachable.
    """
    idx = index(ledger)
    result = Result()
    left = r1(r0(ledger, idx, result), idx, result)
    if through in ("R2", "R3"):
        left = r2(left, idx, result)
    if through == "R3":
        if propose is None:
            raise ValueError("R3 needs a proposer; pass propose= or stop at R2")
        left = r3(left, idx, result, propose)
    result.unmatched_credits = [c["bank_ref"] for c in left]
    result.unmatched_settlements = [s["settlement_id"] for s in idx.unclaimed()]
    return result

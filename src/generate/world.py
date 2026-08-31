"""A perfectly tied set of books. Nothing here is broken on purpose.

`breaks.py` does the damage afterwards and records what it did, so the answer key is a log
of the injuries rather than a re-reading of the wreckage. Build clean, assert the identity,
then injure.

No floats: this module lives under src/ and the no-float scan covers it. Randomness goes
through `chance()` and `randrange`, never `rng.random()`, which returns a float.
"""

import csv
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path
from random import Random

from money import Paise, mul_bps

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 3, 31)
N_PAYMENTS = 5000
SETTLEMENT_LAG_DAYS = 2  # T+2 business days, Razorpay standard

# The generator keeps its OWN rate card. src/audit/ must not import this one -- an auditor
# that shares a constant with the generator is testing that a variable equals itself.
FEE_BPS = {"upi": 0, "card": 200, "netbanking": 190, "wallet": 220}
GST_BPS = 1800
METHOD_WEIGHTS = {"upi": 62, "card": 22, "netbanking": 10, "wallet": 6}

# --- structural knobs: these, not the break rates, decide the rung split (PRD 8) ---
BUNDLE_BPS = 1200           # credits carrying more than one settlement -- R2's whole reason
BUNDLE_MIN, BUNDLE_MAX = 2, 5
UTR_TREATMENT_BPS = {"verbatim": 7800, "truncated": 1200, "garbled": 600, "absent": 400}

# Decoys are the only reason E14 can be scored. The window and the size are R2's own
# parameters from PRD 5, not free choices: a decoy outside R2's window is filtered out before
# the solver runs, and one outside R2's subset size is never enumerated. Either way it tests
# nothing. The values are restated here rather than imported, because a generator sharing a
# constant with the matcher would make the test below assert a variable equals itself -- so
# `test_the_decoy_knobs_still_equal_r2s_own` asserts the two agree and fails when they drift.
# There is no decoy *rate*. A decoy needs a rival subset that survives the ladder, and at
# this scale the window rarely offers one -- so the generator attempts every bundled credit
# and builds wherever a construction exists, which comes out at one or two per seed. A rate
# would be a number held rather than measured; see PRD 8.
DECOY_WINDOW_DAYS = 6       # R2's window, and derived the same way -- see PRD 5
DECOY_MIN, DECOY_MAX = 2, 5
DECOY_GAP_MIN = 60_000      # two payments' smallest possible net; one cannot close odd paise
# The host takes the added payments. Thirty-five puts a median settlement at 91, still well
# under the 90th percentile of the natural spread (~150) and nowhere near its max (~240), so
# a filled settlement does not stand out by volume any more than it does by price.
DECOY_FILL_MAX = 35

REFUND_BPS = 400            # normal, fully linked refunds
CHARGEBACK_BPS = 40
ADJUSTMENT_BPS = 300
ABANDONED_ORDER_BPS = 800   # carts, not exceptions -- see the E07 qualifier in PRD 8

AMOUNT_BANDS = [((299, 799), 45), ((799, 1499), 30), ((1499, 3499), 18), ((3499, 8999), 7)]

FIRST_NAMES = [
    "Aarav", "Ananya", "Rohan", "Priya", "Vikram", "Sneha", "Arjun", "Kavya", "Rahul",
    "Meera", "Karthik", "Divya", "Siddharth", "Nandini", "Imran", "Fatima", "Joseph",
    "Anjali", "Manish", "Ritu", "Sandeep", "Pooja", "Harish", "Lakshmi", "Tanvi",
]
LAST_NAMES = [
    "Sharma", "Reddy", "Iyer", "Patel", "Nair", "Gupta", "Menon", "Desai", "Rao",
    "Bose", "Chatterjee", "Khan", "Fernandes", "Joshi", "Kulkarni", "Pillai", "Mehta",
]
# Metro-weighted, real pincode ranges. Random six-digit numbers read as fake to anyone
# who lives at one of these.
PINCODES = [
    ("Bengaluru", 560001, 560103, 22), ("Mumbai", 400001, 400104, 20),
    ("Delhi", 110001, 110096, 15), ("Hyderabad", 500001, 500098, 11),
    ("Chennai", 600001, 600119, 9), ("Pune", 411001, 411057, 8),
    ("Kolkata", 700001, 700157, 6), ("Ahmedabad", 380001, 380063, 4),
    ("Jaipur", 302001, 302039, 3), ("Kochi", 682001, 682042, 2),
]

NARRATIONS = [
    "NEFT-RAZORPAY SOFTWARE PRIVA-{utr}-HDFC-XXXXX",
    "IMPS/{utr}/RAZORPAYSOFTWARE/SETTLEMENT",
    "NEFT CR-HDFC0000060-RAZORPAY SOFTWARE PVT LTD-{utr}",
    "RTGS-{utr}-RAZORPAY SOFTWARE PRIVATE LIMITED-SETTL",
    "UPI/CR/{utr}/RAZORPAY/HDFC/SETTLEMENT",
]
IDCHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def chance(rng: Random, bps: int) -> bool:
    """True with probability bps/10000. Not rng.random() < rate -- that is a float."""
    return rng.randrange(10_000) < bps


def _rid(rng: Random, prefix: str) -> str:
    return prefix + "".join(rng.choices(IDCHARS, k=14))


def _pick(rng: Random, weighted: dict) -> str:
    return rng.choices(list(weighted), weights=list(weighted.values()), k=1)[0]


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _day_weight(d: date) -> int:
    """Weekend dip and a month-end spike, both real in Indian D2C order data."""
    weight = 85 if d.weekday() >= 5 else 100
    if (d + timedelta(days=3)).month != d.month:
        weight = weight * 2
    return weight


def _add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


@dataclass
class World:
    seed: int
    orders: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    settlements: list[dict] = field(default_factory=list)
    bank: list[dict] = field(default_factory=list)
    matches: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    expected_fees: dict[str, dict] = field(default_factory=dict)
    labels: list[dict] = field(default_factory=list)
    protected_settlements: set[str] = field(default_factory=set)
    protected_refs: set[str] = field(default_factory=set)
    credit_of_settlement: dict[str, str] = field(default_factory=dict)
    narration_template: dict[str, str] = field(default_factory=dict)
    payments_of_settlement: dict[str, list[str]] = field(default_factory=dict)
    decoys_attempted: int = 0
    decoys_feasible: int = 0
    in_transit_paise: int = 0
    credit_before_breaks: int = 0
    timing_moved_paise: int = 0

    def payment(self, pid: str) -> dict:
        return self._index(self.payments, "payment_id")[pid]

    def settlement(self, sid: str) -> dict:
        return self._index(self.settlements, "settlement_id")[sid]

    def credit(self, ref: str) -> dict:
        return self._index(self.bank, "bank_ref")[ref]

    def _index(self, rows: list[dict], key: str) -> dict[str, dict]:
        return {row[key]: row for row in rows}


def build(seed: int) -> World:
    rng = Random(seed)
    w = World(seed=seed)

    days = _days(PERIOD_START, PERIOD_END)
    weights = [_day_weight(d) for d in days]
    for day in rng.choices(days, weights=weights, k=N_PAYMENTS):
        _order_and_payment(w, rng, day)
    for _ in range(N_PAYMENTS * ABANDONED_ORDER_BPS // 10_000):
        _abandoned_order(w, rng, rng.choices(days, weights=weights, k=1)[0])

    _refunds(w, rng)
    _settlements(w, rng)
    _credits(w, rng)
    _decoys(w, rng)
    # A fill on an in-transit host raises a net that `_credits` already totalled.
    recompute_in_transit(w)

    w.expected_fees = {
        p["payment_id"]: {"fee_paise": p["fee_paise"], "gst_paise": p["gst_paise"]}
        for p in w.payments
    }
    w.credit_before_breaks = sum(row["credit_paise"] for row in w.bank)
    return w


def _amount(rng: Random) -> Paise:
    """Whole-rupee prices, as a real catalogue has. Sub-rupee noise comes from fees."""
    bands = [b for b, _ in AMOUNT_BANDS]
    lo, hi = rng.choices(bands, weights=[wt for _, wt in AMOUNT_BANDS], k=1)[0]
    return Paise(rng.randrange(lo, hi) * 100)


def _customer(rng: Random) -> tuple[str, str]:
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    city = rng.choices(PINCODES, weights=[p[3] for p in PINCODES], k=1)[0]
    return name, str(rng.randrange(city[1], city[2] + 1))


def _order_and_payment(w: World, rng: Random, day: date,
                       amount: Paise | None = None, method: str | None = None) -> dict:
    """`amount` and `method` are chosen for you unless a caller needs a specific one --
    `_decoys` does, to land a settlement's net on an exact figure. Returns the payment."""
    amount = _amount(rng) if amount is None else amount
    name, pincode = _customer(rng)
    order_id = _rid(rng, "order_")
    w.orders.append({
        "order_id": order_id,
        "created_at": day.strftime("%d/%m/%Y"),
        "customer_ref": _rid(rng, "cust_")[:12],
        "customer_name": name,
        "pincode": pincode,
        "gross_amount_paise": amount,
        "status": "paid",
    })
    method = _pick(rng, METHOD_WEIGHTS) if method is None else method
    fee = mul_bps(amount, FEE_BPS[method])
    payment = {
        "payment_id": _rid(rng, "pay_"),
        "order_id": order_id,
        "captured_at": f"{day.isoformat()} {rng.randrange(6, 23):02d}:"
                       f"{rng.randrange(60):02d}:{rng.randrange(60):02d}",
        "amount_paise": amount,
        "method": method,
        "fee_paise": fee,
        "gst_paise": mul_bps(fee, GST_BPS),
        "settlement_id": "",
        "status": "captured",
        "_day": day,
    }
    w.payments.append(payment)
    return payment


def _abandoned_order(w: World, rng: Random, day: date) -> None:
    name, pincode = _customer(rng)
    w.orders.append({
        "order_id": _rid(rng, "order_"),
        "created_at": day.strftime("%d/%m/%Y"),
        "customer_ref": _rid(rng, "cust_")[:12],
        "customer_name": name,
        "pincode": pincode,
        "gross_amount_paise": _amount(rng),
        "status": "created",
    })


def _refunds(w: World, rng: Random) -> None:
    for p in w.payments:
        kind = None
        if chance(rng, REFUND_BPS):
            kind = "refund"
        elif chance(rng, CHARGEBACK_BPS):
            kind = "chargeback"
        if kind is None:
            continue
        raised = p["_day"] + timedelta(days=rng.randrange(3, 21))
        if _add_business_days(raised, SETTLEMENT_LAG_DAYS) > PERIOD_END:
            continue
        w.refunds.append({
            "refund_id": _rid(rng, "rfnd_"),
            "payment_id": p["payment_id"],
            "created_at": raised.isoformat(),
            "amount_paise": p["amount_paise"],
            "type": kind,
            "settlement_id": "",
            "status": "processed",
            "_settles_on": _add_business_days(raised, SETTLEMENT_LAG_DAYS),
        })
        p["status"] = "refunded"


def _settlements(w: World, rng: Random) -> None:
    by_date: dict[date, list[dict]] = {}
    for p in w.payments:
        by_date.setdefault(_add_business_days(p["_day"], SETTLEMENT_LAG_DAYS), []).append(p)

    for settled_on in sorted(by_date):
        sid = _rid(rng, "setl_")
        for p in by_date[settled_on]:
            p["settlement_id"] = sid
        w.settlements.append({
            "settlement_id": sid,
            "settled_at": settled_on.strftime("%d-%b-%y"),
            "utr": str(rng.randrange(10**11, 10**12)),
            "net_amount_paise": 0,
            "fee_paise": sum(p["fee_paise"] for p in by_date[settled_on]),
            "gst_paise": sum(p["gst_paise"] for p in by_date[settled_on]),
            "refund_paise": 0,
            "adjustment_paise": 0,
            "_settled_on": settled_on,
        })
        w.payments_of_settlement[sid] = [p["payment_id"] for p in by_date[settled_on]]

    dates = sorted(by_date)
    for r in w.refunds:
        landing = next((d for d in dates if d >= r["_settles_on"]), None)
        if landing is None:
            continue
        sid = w.settlements[dates.index(landing)]["settlement_id"]
        r["settlement_id"] = sid

    for s in w.settlements:
        if chance(rng, ADJUSTMENT_BPS):
            sign = -1 if chance(rng, 5000) else 1
            s["adjustment_paise"] = sign * rng.randrange(100, 50_000)
        s["refund_paise"] = sum(
            r["amount_paise"] for r in w.refunds if r["settlement_id"] == s["settlement_id"]
        )
        gross = sum(w.payment(pid)["amount_paise"] for pid in w.payments_of_settlement[s["settlement_id"]])
        s["net_amount_paise"] = (
            gross - s["fee_paise"] - s["gst_paise"] - s["refund_paise"] + s["adjustment_paise"]
        )


def _absent(template: str) -> str:
    """The narration a credit carries when its UTR did not survive the wire."""
    return template.replace("{utr}", "").replace("--", "-")


def _narration(rng: Random, utr: str) -> tuple[str, str]:
    """UTR recoverability is the entire R0/R1/R3 boundary -- see the knobs in PRD 8.

    Returns the text and the template behind it. `_decoys` needs the template to re-render a
    credit as UTR-absent later without drawing from `rng` and shifting every downstream seed.
    """
    treatment = _pick(rng, UTR_TREATMENT_BPS)
    template = rng.choice(NARRATIONS)
    if treatment == "absent":
        return _absent(template), template
    if treatment == "truncated":
        utr = utr[:rng.randrange(5, 9)]
    if treatment == "garbled":
        i = rng.randrange(len(utr))
        utr = utr[:i] + rng.choice("OIlS8B") + utr[i + 1:]
    return template.format(utr=utr), template


def _credits(w: World, rng: Random) -> None:
    settled = [s for s in w.settlements if s["_settled_on"] <= PERIOD_END]
    w.in_transit_paise = sum(
        s["net_amount_paise"] for s in w.settlements if s["_settled_on"] > PERIOD_END
    )
    for s in w.settlements:
        if s["_settled_on"] > PERIOD_END:
            w.labels.append({
                "record_type": "settlement", "record_id": s["settlement_id"],
                "code": "E12", "delta_paise": 0,
            })

    i = 0
    while i < len(settled):
        size = 1
        if chance(rng, BUNDLE_BPS):
            size = min(rng.randrange(BUNDLE_MIN, BUNDLE_MAX + 1), len(settled) - i)
        group = settled[i:i + size]
        i += size

        ref = f"HDFC{rng.randrange(10**8, 10**9)}"
        text, template = _narration(rng, group[0]["utr"])
        w.narration_template[ref] = template
        w.bank.append({
            "txn_date": max(s["_settled_on"] for s in group).strftime("%d/%m/%Y"),
            "narration": text,
            "credit_paise": sum(s["net_amount_paise"] for s in group),
            "debit_paise": 0,
            "closing_balance_paise": 0,
            "bank_ref": ref,
        })
        for s in group:
            w.credit_of_settlement[s["settlement_id"]] = ref
        w.matches.append({
            "bank_ref": ref,
            "settlement_ids": [s["settlement_id"] for s in group],
            "payment_ids": [pid for s in group for pid in w.payments_of_settlement[s["settlement_id"]]],
        })


def _net_of(amount: int, method: str) -> int:
    """What one payment adds to its settlement's net: amount, less fee, less GST on the fee."""
    fee = mul_bps(Paise(amount), FEE_BPS[method])
    return amount - fee - mul_bps(Paise(fee), GST_BPS)


@cache
def _net_table() -> dict[int, tuple[int, str]]:
    """Every net a single whole-rupee payment can contribute, mapped back to what makes it."""
    lo = min(band[0] for band, _ in AMOUNT_BANDS)
    hi = max(band[1] for band, _ in AMOUNT_BANDS)
    table: dict[int, tuple[int, str]] = {}
    for method in FEE_BPS:
        for rupees in range(lo, hi):
            table.setdefault(_net_of(rupees * 100, method), (rupees * 100, method))
    return table


def _closing_payments(rng: Random, gap: int) -> list[tuple[int, str]] | None:
    """One or two ordinary payments whose nets add to exactly `gap` paise, or None.

    This is the whole trick, and it needs two payments rather than one. A settlement's net
    carries sub-rupee digits because GST rounds on the fee, so the gap is almost never a
    whole rupee and a UPI payment -- which pays no fee and contributes its amount unchanged
    -- cannot close it. The fee-bearing methods do land on odd paise, but a payment's net
    rises monotonically with its amount, so any one method hits only about one paise value
    in a hundred. Two payments searched against each other reach essentially all of them.

    The alternative is inventing a payment priced in paise, which would be the one row in
    five thousand that does not look like the others -- the leak this construction exists to
    avoid. Search starts at a random offset so the closers are not all drawn from the cheap
    end of the catalogue.
    """
    table = _net_table()
    if gap in table:
        return [table[gap]]
    keys = list(table)
    start = rng.randrange(len(keys))
    for i in range(len(keys)):
        first = keys[(start + i) % len(keys)]
        second = gap - first
        if second in table:
            return [table[first], table[second]]
    return None


def _decoy_subset(pool: list[dict], target: int) -> tuple[list[dict], int] | None:
    """The subset of `pool` sitting closest below `target`, with the gap left to close.

    Below, not nearest: the gap is closed by adding payments, and payments only add. The
    smallest qualifying gap is also the most fillable, so `_fill` refusing this one means no
    other subset would have worked either. Ties break on enumeration order, which is fixed
    because `pool` arrives sorted, so the same seed builds the same decoy.
    """
    best = None
    for size in range(DECOY_MIN, DECOY_MAX + 1):
        for combo in combinations(pool, size):
            gap = target - sum(s["net_amount_paise"] for s in combo)
            if gap >= DECOY_GAP_MIN and (best is None or gap < best[1]):
                best = (list(combo), gap)
    return best


def _decoys(w: World, rng: Random) -> None:
    """A second subset of settlements that ties to the paisa, so R2 finds two valid answers
    and has to refuse. PRD 6, E14 -- an ambiguity, not a break: nothing is wrong with the
    money, the evidence simply does not single out one answer.

    **A rival subset has to survive the ladder to be a rival at all.** The first version of
    this built decoys out of solo-credited settlements, which is arithmetically correct and
    completely inert: R0 or R1 claims each of those against its own bank credit long before
    R2 runs, so by the time the solver enumerates, only the true subset is left open and it
    matches it. Ambiguity is a property of what is still unclaimed when R2 starts, not of the
    arithmetic alone. The pool here is therefore the settlements that reach R2: those inside
    *other* bundled credits, which no single-settlement rung can claim, and those in transit,
    which have no credit to be claimed against.

    R2 spends no tolerance, so the tie must be exact, and an exact tie cannot be arranged by
    moving `net_amount_paise` or `adjustment_paise` after the fact. Moving the net alone
    desynchronises a settlement from the payments inside it; moving the adjustment keeps the
    arithmetic honest but not the data, because the gap runs to lakhs and every real
    adjustment is under 500 rupees. So the contents are chosen instead: the gap between the
    decoy's net and the target credit is closed with ordinary payments added to one
    settlement inside it, the last one or two picked so the total lands exactly.

    The target's narration gives up its UTR, because PRD 5 lets R2 use a reference naming a
    settlement in one subset as evidence -- and it would, since the narration carries a true
    subset member's UTR. An ambiguity the evidence resolves is not an ambiguity.

    Runs after `_credits`, because a decoy is built against a known target, and before
    `breaks.injure`, which is why the records go into the protected sets: a break that shifts
    either side of an engineered equality deletes an E14 silently.
    """
    match_of_ref = {m["bank_ref"]: m for m in w.matches}
    bundles = {m["bank_ref"]: set(m["settlement_ids"]) for m in w.matches
               if len(m["settlement_ids"]) > 1}
    in_bundle = {sid for ids in bundles.values() for sid in ids}
    in_transit = {s["settlement_id"] for s in w.settlements
                  if s["settlement_id"] not in w.credit_of_settlement}
    survives_the_ladder = in_bundle | in_transit

    w.decoys_attempted = len(bundles)
    used: set[str] = set()

    for ref, true_subset in bundles.items():
        if not DECOY_MIN <= len(true_subset) <= DECOY_MAX:
            continue                      # outside R2's subset size; it would never enumerate it
        if used & true_subset:
            continue
        day = max(w.settlement(sid)["_settled_on"] for sid in true_subset)
        pool = [
            w.settlement(sid)
            for sid in sorted(survives_the_ladder - true_subset - used)
            if abs((w.settlement(sid)["_settled_on"] - day).days) <= DECOY_WINDOW_DAYS
        ]
        found = _decoy_subset(pool, w.credit(ref)["credit_paise"])
        if found is None:
            continue
        decoy, gap = found
        added = _fill(w, rng, rng.choice(decoy), gap, match_of_ref)
        if added is None:
            continue

        w.credit(ref)["narration"] = _absent(w.narration_template[ref])
        ids = sorted(s["settlement_id"] for s in decoy)
        w.ambiguous.append({
            "bank_ref": ref,
            "true_subset": sorted(true_subset),
            "decoy_subsets": [ids],
            "payments_added": added,
        })
        used |= true_subset | set(ids)
        w.protected_settlements |= true_subset | set(ids)
        w.protected_refs.add(ref)
    w.decoys_feasible = len(w.ambiguous)


def _fill(w: World, rng: Random, host: dict, gap: int, match_of_ref: dict) -> int | None:
    """Add payments to `host` until its net has risen by exactly `gap`. Returns how many.

    Ordinary draws while the gap is wider than one payment, then `_closing_payment` for the
    last. Returns None without touching the world if the remainder turns out unreachable,
    so a decoy is never left half-built.
    """
    floor, ceiling = min(_net_table()), max(_net_table())
    plan: list[tuple[int, str]] = []
    left = gap
    while left > 2 * ceiling:
        if len(plan) > DECOY_FILL_MAX:
            return None
        amount, method = _amount(rng), _pick(rng, METHOD_WEIGHTS)
        if left - _net_of(amount, method) < 2 * floor:
            continue                      # would leave a remainder no two payments can close
        plan.append((amount, method))
        left -= _net_of(amount, method)
    closers = _closing_payments(rng, left)
    if closers is None or len(plan) + len(closers) > DECOY_FILL_MAX:
        return None                       # would push the host outside the natural spread
    plan.extend(closers)

    sid = host["settlement_id"]
    day = w.payment(w.payments_of_settlement[sid][0])["_day"]
    # A host in transit has no credit to move: the payments raise gross and in_transit by the
    # same figure and PRD 8's identity is untouched. A host inside another bundle does have
    # one, and it moves with the settlement so that bundle still ties.
    ref = w.credit_of_settlement.get(sid)
    for amount, method in plan:
        p = _order_and_payment(w, rng, day, Paise(amount), method)
        p["settlement_id"] = sid
        w.payments_of_settlement[sid].append(p["payment_id"])
        host["fee_paise"] += p["fee_paise"]
        host["gst_paise"] += p["gst_paise"]
        host["net_amount_paise"] += _net_of(amount, method)
        if ref is not None:
            w.credit(ref)["credit_paise"] += _net_of(amount, method)
            match_of_ref[ref]["payment_ids"].append(p["payment_id"])
    return len(plan)


def recompute_in_transit(w: World) -> None:
    """Injection moves settlement nets, including uncredited ones. Re-total afterwards."""
    w.in_transit_paise = sum(
        s["net_amount_paise"] for s in w.settlements if s["_settled_on"] > PERIOD_END
    )


def totals(w: World) -> dict:
    return {
        "gross_paise": sum(p["amount_paise"] for p in w.payments),
        "fee_paise": sum(p["fee_paise"] for p in w.payments),
        "gst_paise": sum(p["gst_paise"] for p in w.payments),
        "refund_paise": sum(r["amount_paise"] for r in w.refunds if r["settlement_id"]),
        "adjustment_paise": sum(s["adjustment_paise"] for s in w.settlements),
        "credit_paise": sum(row["credit_paise"] for row in w.bank),
        "in_transit_paise": w.in_transit_paise,
    }


def assert_identity(w: World) -> None:
    """PRD 8. If this fails, the clean world is not clean and nothing downstream means anything."""
    t = totals(w)
    left = (t["gross_paise"] - t["fee_paise"] - t["gst_paise"] - t["refund_paise"]
            + t["adjustment_paise"] - t["in_transit_paise"])
    assert left == t["credit_paise"], f"identity off by {left - t['credit_paise']} paise"


FIELDS = {
    "orders.csv": ["order_id", "created_at", "customer_ref", "customer_name", "pincode",
                   "gross_amount_paise", "status"],
    "payments.csv": ["payment_id", "order_id", "captured_at", "amount_paise", "method",
                     "fee_paise", "gst_paise", "settlement_id", "status"],
    "refunds.csv": ["refund_id", "payment_id", "created_at", "amount_paise", "type",
                    "settlement_id", "status"],
    "settlements.csv": ["settlement_id", "settled_at", "utr", "net_amount_paise",
                        "fee_paise", "gst_paise", "refund_paise", "adjustment_paise"],
    "bank_statement.csv": ["txn_date", "narration", "credit_paise", "debit_paise",
                           "closing_balance_paise", "bank_ref"],
}


def write(w: World, outdir: Path) -> None:
    balance = 10_00_00_000
    for row in w.bank:
        balance = balance + row["credit_paise"] - row["debit_paise"]
        row["closing_balance_paise"] = balance

    outdir.mkdir(parents=True, exist_ok=True)
    for name, rows in [("orders.csv", w.orders), ("payments.csv", w.payments),
                       ("refunds.csv", w.refunds), ("settlements.csv", w.settlements),
                       ("bank_statement.csv", w.bank)]:
        # joinpath, not `/`: the no-float scan reads `/` as true division and it is right
        # to. Path division is the one place the two look alike, and the rule stays absolute.
        with outdir.joinpath(name).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS[name], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

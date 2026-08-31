"""Injection. Every function here damages the world and records exactly what it did.

Two rules hold across this module:

  * A break records `delta_paise` -- the signed effect on money the merchant actually
    receives. Linkage breaks (E06-E09, E13) move no money and record 0.
  * `credit_before_breaks + sum(delta) == sum(credit_paise)` after injection. That is the
    invariant tying the answer key to the CSVs, and it is asserted every run.

Rates are basis points against a NAMED population, because a flat "1.0% of records" is
meaningless when the bank statement has 46 rows and the payments file has 5,000. Each rate
carries a floor of one, so every one of the thirteen codes fires in every dataset.
"""

from datetime import date
from random import Random

from money import Paise, mul_bps

from .world import GST_BPS, IDCHARS, World, chance

# rate_bps against the population named in the comment
FEE_VARIANCE_BPS = 150        # payments
DUPLICATE_PAYMENT_BPS = 80    # payments
ORPHAN_PAYMENT_BPS = 30       # payments        E06
PAID_ORDER_NO_PAYMENT_BPS = 30  # orders        E07
PARTIAL_REFUND_BPS = 2000     # refunds
UNLINKED_REFUND_BPS = 200     # refunds         E08
UNLINKED_CHARGEBACK_BPS = 2000  # chargebacks   E09
MISSING_SETTLEMENT_BPS = 600  # settlements     E02
UNIDENTIFIED_RECEIPT_BPS = 600  # bank rows     E01
UNPARSEABLE_BPS = 800         # bank rows       E13
DRIFT_WITHIN_BPS = 1200       # bank rows       E03, consumes tolerance
DRIFT_OUTSIDE_BPS = 400       # bank rows       E04, a real break

TOLERANCE_PAISE = 100

GARBAGE = [
    "MISC CR 8817726251",
    "CR-TRF-000000000000-B2B",
    "*NEFT*//..//SETTL//",
    "TRANSFER FROM 50100XXXXXXXX",
]


def _sample(rng: Random, pop: list, bps: int) -> list:
    """Floor of one: a code with no rows is a code the eval can never score."""
    if not pop:
        return []
    return rng.sample(pop, min(len(pop), max(1, len(pop) * bps // 10_000)))


def _unprotected(w: World, rows: list[dict], key: str) -> list[dict]:
    """Drop the records `world._decoys` engineered an exact tie across.

    A break that shifts a settlement inside a decoy's subset -- or drifts the credit both
    subsets tie to -- moves one side of that equality and deletes an E14 with no trace. The
    E14 population is two or three rows, so one silent loss is a third of it. Only the
    money-moving breaks filter; E06-E09 and E13 move nothing and are left alone.
    """
    guard = w.protected_refs if key == "bank_ref" else w.protected_settlements
    return [r for r in rows if r[key] not in guard]


def injure(w: World, rng: Random) -> list[dict]:
    breaks: list[dict] = list(w.labels)
    for fn in (_fee_variance, _duplicate_payment, _partial_refund, _missing_settlement,
               _unidentified_receipt, _unparseable_narration, _rounding_drift,
               _orphan_payment, _paid_order_no_payment, _unlinked_refund,
               _unlinked_chargeback):
        breaks.extend(fn(w, rng))
    return breaks


def _shift(w: World, sid: str, delta: int) -> int:
    """Move a settlement's net and whatever bank credit carries it, together.

    Returns what actually reached the bank. A settlement that has not been credited yet --
    in transit past the period end -- moves no money this period, so the break is still
    real but its `delta_paise` is 0. Claiming otherwise puts rupees in the answer key that
    are in no bank statement.
    """
    w.settlement(sid)["net_amount_paise"] += delta
    ref = w.credit_of_settlement.get(sid)
    if ref is None:
        return 0
    w.credit(ref)["credit_paise"] += delta
    return delta


def _fee_variance(w: World, rng: Random) -> list[dict]:
    """E05. Both directions -- an aggregator that undercharges is still off contract."""
    out = []
    for p in _sample(rng, _unprotected(w, w.payments, "settlement_id"), FEE_VARIANCE_BPS):
        sign = -1 if chance(rng, 4000) else 1
        drift = sign * rng.randrange(50, 800)
        old_fee, old_gst = p["fee_paise"], p["gst_paise"]
        p["fee_paise"] = max(0, old_fee + drift)
        p["gst_paise"] = mul_bps(Paise(p["fee_paise"]), GST_BPS)
        moved = (p["fee_paise"] + p["gst_paise"]) - (old_fee + old_gst)
        s = w.settlement(p["settlement_id"])
        s["fee_paise"] += p["fee_paise"] - old_fee
        s["gst_paise"] += p["gst_paise"] - old_gst
        applied = _shift(w, p["settlement_id"], -moved)
        out.append({"record_type": "payment", "record_id": p["payment_id"],
                    "code": "E05", "delta_paise": applied})
    return out


def _duplicate_payment(w: World, rng: Random) -> list[dict]:
    """E10. The same order captured twice -- the merchant is paid twice and owes a refund."""
    out = []
    for p in _sample(rng, _unprotected(w, w.payments, "settlement_id"), DUPLICATE_PAYMENT_BPS):
        dup = dict(p)
        dup["payment_id"] = p["payment_id"][:4] + "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=14))
        w.payments.append(dup)
        w.payments_of_settlement[p["settlement_id"]].append(dup["payment_id"])
        net = dup["amount_paise"] - dup["fee_paise"] - dup["gst_paise"]
        applied = _shift(w, p["settlement_id"], net)
        ref = w.credit_of_settlement.get(p["settlement_id"])
        for m in w.matches:
            if m["bank_ref"] == ref:
                m["payment_ids"].append(dup["payment_id"])
        out.append({"record_type": "payment", "record_id": dup["payment_id"],
                    "code": "E10", "delta_paise": applied})
    return out


def _partial_refund(w: World, rng: Random) -> list[dict]:
    """E11. A refund settles for less than it was raised for and the remainder drifts."""
    out = []
    linked = _unprotected(w, [r for r in w.refunds if r["settlement_id"]], "settlement_id")
    for r in _sample(rng, linked, PARTIAL_REFUND_BPS):
        old = r["amount_paise"]
        r["amount_paise"] = old * rng.randrange(30, 85) // 100
        held_back = old - r["amount_paise"]
        s = w.settlement(r["settlement_id"])
        s["refund_paise"] -= held_back
        applied = _shift(w, r["settlement_id"], held_back)
        out.append({"record_type": "refund", "record_id": r["refund_id"],
                    "code": "E11", "delta_paise": applied})
    return out


def _missing_settlement(w: World, rng: Random) -> list[dict]:
    """E02. Settled on the aggregator's books, never landed in the bank."""
    solo = [s for s in w.settlements
            if sum(1 for k, v in w.credit_of_settlement.items()
                   if v == w.credit_of_settlement.get(s["settlement_id"])) == 1]
    out = []
    for s in _sample(rng, solo, MISSING_SETTLEMENT_BPS):
        ref = w.credit_of_settlement.pop(s["settlement_id"])
        w.bank[:] = [row for row in w.bank if row["bank_ref"] != ref]
        w.matches[:] = [m for m in w.matches if m["bank_ref"] != ref]
        out.append({"record_type": "settlement", "record_id": s["settlement_id"],
                    "code": "E02", "delta_paise": -s["net_amount_paise"]})
    return out


def _unidentified_receipt(w: World, rng: Random) -> list[dict]:
    """E01. Money arrived. Nobody knows what for."""
    out = []
    for _ in range(max(1, len(w.bank) * UNIDENTIFIED_RECEIPT_BPS // 10_000)):
        amount = rng.randrange(50_000, 8_00_000)
        ref = f"HDFC{rng.randrange(10**8, 10**9)}"
        w.bank.append({
            "txn_date": date(2026, rng.randrange(1, 4), rng.randrange(1, 28)).strftime("%d/%m/%Y"),
            "narration": rng.choice(GARBAGE),
            "credit_paise": amount, "debit_paise": 0,
            "closing_balance_paise": 0, "bank_ref": ref,
        })
        out.append({"record_type": "bank", "record_id": ref,
                    "code": "E01", "delta_paise": amount})
    return out


def _unparseable_narration(w: World, rng: Random) -> list[dict]:
    """E13. The credit is fine. The string describing it is not."""
    out = []
    for row in _sample(rng, [r for r in w.bank if r["credit_paise"]], UNPARSEABLE_BPS):
        row["narration"] = rng.choice(GARBAGE)
        out.append({"record_type": "bank", "record_id": row["bank_ref"],
                    "code": "E13", "delta_paise": 0})
    return out


def _rounding_drift(w: World, rng: Random) -> list[dict]:
    """E03 inside tolerance, E04 outside it. The line between them is 100 paise, exactly."""
    out = []
    pool = _unprotected(w, [r for r in w.bank if r["credit_paise"]], "bank_ref")
    within = _sample(rng, pool, DRIFT_WITHIN_BPS)
    rest = [r for r in pool if r not in within]  # no row drifts twice
    for row, code in ([(r, "E03") for r in within]
                      + [(r, "E04") for r in _sample(rng, rest, DRIFT_OUTSIDE_BPS)]):
        span = (1, TOLERANCE_PAISE) if code == "E03" else (TOLERANCE_PAISE + 50, 90_000)
        drift = rng.randrange(*span) * (-1 if chance(rng, 5000) else 1)
        row["credit_paise"] += drift
        out.append({"record_type": "bank", "record_id": row["bank_ref"],
                    "code": code, "delta_paise": drift})
    return out


def _orphan_payment(w: World, rng: Random) -> list[dict]:
    """E06. Unlink, do not invent -- money is unchanged, only the trail is cut."""
    out = []
    for p in _sample(rng, [p for p in w.payments if p["order_id"]], ORPHAN_PAYMENT_BPS):
        p["order_id"] = ""
        out.append({"record_type": "payment", "record_id": p["payment_id"],
                    "code": "E06", "delta_paise": 0})
    return out


def _paid_order_no_payment(w: World, rng: Random) -> list[dict]:
    """E07, qualified: status claims paid. An unpaid order is a cart, not an exception."""
    out = []
    for template in _sample(rng, w.orders, PAID_ORDER_NO_PAYMENT_BPS):
        ghost = dict(template)
        ghost["order_id"] = "order_" + "".join(rng.choices(IDCHARS, k=14))
        ghost["status"] = "paid"
        w.orders.append(ghost)
        out.append({"record_type": "order", "record_id": ghost["order_id"],
                    "code": "E07", "delta_paise": 0})
    return out


def _unlinked_refund(w: World, rng: Random) -> list[dict]:
    out = []
    for r in _sample(rng, [r for r in w.refunds if r["type"] == "refund"], UNLINKED_REFUND_BPS):
        r["payment_id"] = ""
        out.append({"record_type": "refund", "record_id": r["refund_id"],
                    "code": "E08", "delta_paise": 0})
    return out


def _unlinked_chargeback(w: World, rng: Random) -> list[dict]:
    out = []
    for r in _sample(rng, [r for r in w.refunds if r["type"] == "chargeback"],
                     UNLINKED_CHARGEBACK_BPS):
        r["payment_id"] = ""
        out.append({"record_type": "refund", "record_id": r["refund_id"],
                    "code": "E09", "delta_paise": 0})
    return out

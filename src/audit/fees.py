"""The fee variance audit. PRD 7 -- the thing that turns a match rate into a rupee number.

Two findings come out of here and they are different in kind:

  * **E05, fee variance.** The aggregator charged something other than the contract. An error,
    and a merchant can dispute it.
  * **Fee spent on refunded revenue.** The aggregator charged correctly and the revenue went
    back. Nothing to dispute and no exception code -- see `refund_fee_burden`.

Reporting the second as a variance would be wrong twice: it invents a dispute the merchant
cannot win, and it inflates the first number, which is the one that has to survive scrutiny.

No floats: this module is under src/ and the no-float scan covers it. Rates are basis points
and `mul_bps` rounds half away from zero, which matters on the refund reversals where a plain
floor would under-charge every negative amount.
"""

from dataclasses import dataclass

from ingest.load import Ledger
from money import Paise, mul_bps

# --- the contract ---------------------------------------------------------------------
#
# PROVENANCE: these are not measured from the data and must never be. They are the merchant's
# contracted rates as stated in PRD 7, which is their single owner -- a claim about a real
# commercial agreement, sourced from the spec, current as of *(PRD 7, 2026-09-01)*. If a
# merchant's actual contract differs, this dict is what changes.
#
# It is deliberately NOT bound to `generate.world.FEE_BPS`. The generator holds its own copy
# and injects variance *against* it, so the two must be free to disagree -- that disagreement
# is the entire signal this module exists to find. A test asserting the two cards match would
# assert that the audit finds nothing, and a test asserting this card against itself is the
# DECOY_MAX tautology in a new place. `test_the_rate_card_is_the_one_in_the_prd` binds it to
# PRD 7 instead, so the spec owns the values and drift on either side is visible.
FEE_BPS = {"upi": 0, "card": 200, "netbanking": 190, "wallet": 220}
GST_BPS = 1800          # on the fee, not on the payment

# The method set is closed. A payment carrying anything else is an ingest failure, not a
# payment billed at zero -- PRD 7. Defaulting the rate would report no variance across a whole
# method, which is the quietest possible way to be wrong.
METHODS = frozenset(FEE_BPS)


@dataclass(frozen=True)
class Variance:
    """One payment billed off contract. `delta_paise` is positive when overcharged."""

    payment_id: str
    method: str
    amount_paise: Paise
    expected_paise: Paise        # fee + GST the contract says
    actual_paise: Paise          # fee + GST actually charged
    delta_paise: Paise

    @property
    def overcharged(self) -> bool:
        return int(self.delta_paise) > 0


def expected_of(amount_paise: int, method: str) -> tuple[Paise, Paise]:
    """Contracted fee and GST for one payment. GST applies to the fee, not to the payment."""
    if method not in METHODS:
        raise KeyError(
            f"payment method {method!r} is not in the contract ({', '.join(sorted(METHODS))}) "
            f"-- it has no rate, so it cannot be audited and must not be billed at zero")
    fee = mul_bps(Paise(amount_paise), FEE_BPS[method])
    return fee, mul_bps(fee, GST_BPS)


def audit_fees(ledger: Ledger) -> list[Variance]:
    """Every payment whose fee plus GST differs from the contract, in either direction.

    Both directions on purpose: an aggregator that undercharges is still off contract, and a
    merchant who only ever hears about overcharges has no way to know the card is wrong rather
    than the billing.
    """
    out = []
    for p in ledger.payments:
        fee, gst = expected_of(p["amount_paise"], p["method"])
        expected = int(fee) + int(gst)
        actual = p["fee_paise"] + p["gst_paise"]
        if expected != actual:
            out.append(Variance(
                payment_id=p["payment_id"], method=p["method"],
                amount_paise=Paise(p["amount_paise"]),
                expected_paise=Paise(expected), actual_paise=Paise(actual),
                delta_paise=Paise(actual - expected)))
    return out


def totals(variances: list[Variance]) -> dict[str, int]:
    """Gross over, gross under, and net -- never the net alone.

    The generator injects variance in both directions and a real aggregator misconfigures in
    both, so a single net figure lets an overcharge and an undercharge cancel into "no
    finding". That is the same hiding place the second identity test exists to close: a sum
    over a population can be right for compensating wrong reasons. Report all three.
    """
    over = sum(int(v.delta_paise) for v in variances if int(v.delta_paise) > 0)
    under = sum(int(v.delta_paise) for v in variances if int(v.delta_paise) < 0)
    return {
        "overcharged_paise": over, "overcharged_count": sum(1 for v in variances if v.overcharged),
        "undercharged_paise": under,
        "undercharged_count": sum(1 for v in variances if not v.overcharged),
        "net_paise": over + under, "payments": len(variances),
    }


def refund_fee_burden(ledger: Ledger) -> dict[str, int]:
    """Fee and GST permanently spent on revenue that was given back.

    **This is not a variance and carries no exception code.** MDR is not reversed on refunds in
    India -- the gateway keeps the fee whether or not the sale survives -- so every one of these
    charges is correct under the contract. There is nothing to dispute and nothing to fix. It is
    reported because a merchant refunding heavily is paying a real cost that appears in no
    statement as a line item, and seeing it is the whole value.

    Giving it a code would put it in the exception list beside things that are wrong, and a
    controller would spend an investigation on a correct charge. Counted only over refunds that
    join to a payment; an unlinked refund (E08/E09) has no fee to attribute.
    """
    payments = {p["payment_id"]: p for p in ledger.payments}
    fee = gst = joined = 0
    for r in ledger.refunds:
        p = payments.get(r["payment_id"])
        if p is None:
            continue
        joined += 1
        fee += p["fee_paise"]
        gst += p["gst_paise"]
    return {
        "refunds_joined": joined, "fee_paise": fee, "gst_paise": gst,
        "total_paise": fee + gst,
        "refunds_unlinked": len(ledger.refunds) - joined,
    }

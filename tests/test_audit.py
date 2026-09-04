"""The fee variance audit. PRD 7.

The rate card is the riskiest constant in the codebase: two copies exist, the generator's and
this one, and they are *required to disagree* -- the generator injects variance against its own
card, and that disagreement is the entire signal the audit looks for. So neither of the obvious
tests is available. Binding the two cards to each other would assert the audit finds nothing.
Asserting this card against itself is `DECOY_MAX == DECOY_MAX` in a new place.

The card is therefore bound to **PRD 7**, which is its single owner. Drift on either side --
the spec changing without the code, or the code changing without the spec -- fails here.
"""

import ast
import json
import re
from pathlib import Path

import pytest

from audit import audit_fees, refund_fee_burden
from audit.fees import FEE_BPS, GST_BPS, METHODS, expected_of, totals
from ingest.load import load
from money import Paise

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ["train", "heldout"]


@pytest.fixture(scope="module", params=SEEDS)
def seed(request):
    ledger = load(ROOT.joinpath("data", request.param))
    truth = json.loads(ROOT.joinpath("eval", "ground_truth", f"{request.param}.json")
                       .read_text(encoding="utf-8"))
    return request.param, ledger, truth


def test_the_rate_card_is_the_one_in_the_prd():
    """PRD 7 owns these values; the code carries a copy. This is the seam between them.

    Not bound to `generate.world.FEE_BPS` on purpose -- see this module's docstring. The two
    cards must be free to disagree, and PRD 7 is the only place that can arbitrate.
    """
    spec = ROOT.joinpath("PRD.md").read_text(encoding="utf-8")
    fee = re.search(r"fee_bps = (\{[^}]*\})", spec)
    gst = re.search(r"gst_bps = (\d+)", spec)
    assert fee and gst, "PRD 7 no longer states the rate card in a parseable form"
    assert ast.literal_eval(fee.group(1)) == FEE_BPS, (
        f"the audit's rate card and PRD 7 disagree: {FEE_BPS} vs {fee.group(1)}")
    assert int(gst.group(1)) == GST_BPS


def test_the_audit_does_not_import_the_generators_rate_card():
    """An auditor sharing a constant with the generator tests that a variable equals itself.

    The same rule as the ground-truth guard, for the same reason: the audit would find zero
    variance by construction and every test of it would pass.
    """
    for path in sorted(ROOT.joinpath("src", "audit").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any("generate" in n for n in names), \
                f"{path.name} imports the generator: {names}"


def test_every_contracted_method_is_exercised(seed):
    """A method with no rows is a rate that could be wrong and never fail a test."""
    _, ledger, _ = seed
    seen = {p["method"] for p in ledger.payments}
    assert METHODS <= seen, f"methods never exercised: {sorted(METHODS - seen)}"


def test_a_method_off_the_contract_is_refused_not_billed_at_zero():
    """PRD 7: the method set is closed. Defaulting an unknown method to 0 bps would report
    no variance across a whole payment method -- the quietest way to be wrong."""
    with pytest.raises(KeyError, match="not in the contract"):
        expected_of(100_000, "cryptocurrency")
    # Asserted on the message, not just the type. Without the explicit guard the bare dict
    # lookup raises KeyError too, so `pytest.raises(KeyError)` alone passes whether or not the
    # guard exists and tests nothing about it -- watched passing on the broken code, which is
    # how this line came to be here.


def test_variance_is_caught_in_both_directions(seed):
    """An aggregator that undercharges is still off contract. A merchant who only ever hears
    about overcharges cannot tell a wrong card from wrong billing."""
    _, ledger, _ = seed
    t = totals(audit_fees(ledger))
    assert t["overcharged_count"] > 0 and t["undercharged_count"] > 0
    assert t["overcharged_paise"] > 0 > t["undercharged_paise"]
    assert t["net_paise"] == t["overcharged_paise"] + t["undercharged_paise"]


def test_gst_is_charged_on_the_fee_not_on_the_payment():
    """The single most expensive arithmetic error available here: GST on 2,500 rupees at
    1800bps is 450 rupees; on the 50-rupee fee it is 9. Off by fifty times."""
    fee, gst = expected_of(2_50_000, "card")
    assert int(fee) == 5000
    assert int(gst) == 900


def test_a_upi_payment_is_free_and_a_card_payment_is_not():
    """UPI at 0bps is why the card is per method: a flat rate makes every UPI payment look
    like a variance and buries the real findings."""
    assert expected_of(1_00_000, "upi") == (Paise(0), Paise(0))
    assert int(expected_of(1_00_000, "card")[0]) == 2000


def test_the_audit_finds_every_labelled_variance_that_is_actually_off_contract(seed):
    """Scored against the labels the data supports, and the gap is named rather than absorbed.

    The answer key labels some E05 rows where no damage was done: `_fee_variance` clamps
    `max(0, old_fee + drift)`, so a negative drift on a UPI payment -- contracted at 0bps --
    leaves the payment exactly on contract and records a break anyway. Those are phantom
    labels, not audit misses; there is nothing in the ledger to find. Queued for the next
    regeneration alongside the E04 defect; see DECISIONS.md, 2026-09-01.
    """
    _, ledger, truth = seed
    labelled = {b["record_id"] for b in truth["breaks"] if b["code"] == "E05"}
    found = {v.payment_id for v in audit_fees(ledger)}
    payments = {p["payment_id"]: p for p in ledger.payments}

    real = set()
    for pid in labelled:
        p = payments[pid]
        fee, gst = expected_of(p["amount_paise"], p["method"])
        if p["fee_paise"] + p["gst_paise"] != int(fee) + int(gst):
            real.add(pid)
    assert real <= found, f"genuinely off-contract payments the audit missed: {real - found}"
    assert labelled - real, "no phantom labels -- has the generator been fixed? update this test"


def test_refund_fee_burden_is_not_a_variance(seed):
    """MDR is not reversed on refunds in India, so every one of these charges is correct.

    It carries no exception code deliberately: putting it in the exception list beside things
    that are wrong would spend a controller's investigation on a correct charge.
    """
    name, ledger, _ = seed
    burden = refund_fee_burden(ledger)
    assert burden["refunds_joined"] > 0 and burden["total_paise"] > 0
    assert burden["fee_paise"] + burden["gst_paise"] == burden["total_paise"]
    payments = {p["payment_id"]: p for p in ledger.payments}
    for r in ledger.refunds:
        p = payments.get(r["payment_id"])
        if p is None:
            continue
        fee, _ = expected_of(p["amount_paise"], p["method"])
        assert p["fee_paise"] >= int(fee) or p["fee_paise"] == 0, \
            f"{name}: {p['payment_id']} looks like a reversed MDR, which no Indian gateway does"

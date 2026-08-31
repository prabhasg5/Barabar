import csv
from collections import Counter

import pytest

from generate import world
from generate.__main__ import SEEDS, build_dataset
from match import ladder

CODES = {f"E{n:02d}" for n in range(1, 14)}


@pytest.fixture(scope="module")
def dataset():
    return build_dataset("train")


def test_clean_world_ties_to_the_paisa():
    """Before any damage, the books must be perfect. If not, nothing downstream means anything."""
    world.assert_identity(world.build(SEEDS["train"]))


def test_answer_key_reconciles_to_the_csvs(dataset):
    """credit_before + sum(delta) == credit_after. Asserted inside build_dataset; pinned here."""
    w, injected, _ = dataset
    after = sum(row["credit_paise"] for row in w.bank)
    assert w.credit_before_breaks + sum(b["delta_paise"] for b in injected) == after


def test_every_code_fires(dataset):
    """Thirteen codes, all of them present. A code with no rows can never fail a test."""
    _, injected, _ = dataset
    assert {b["code"] for b in injected} == CODES


def test_breaks_point_at_records_that_exist(dataset):
    w, injected, _ = dataset
    ids = {
        "payment": {p["payment_id"] for p in w.payments},
        "order": {o["order_id"] for o in w.orders},
        "refund": {r["refund_id"] for r in w.refunds},
        "settlement": {s["settlement_id"] for s in w.settlements},
        "bank": {row["bank_ref"] for row in w.bank},
    }
    missing = [b for b in injected if b["record_id"] not in ids[b["record_type"]]]
    assert not missing, f"answer key cites {len(missing)} records that are not in the CSVs"


def test_matches_point_at_records_that_exist(dataset):
    w, _, _ = dataset
    payments = {p["payment_id"] for p in w.payments}
    settlements = {s["settlement_id"] for s in w.settlements}
    refs = {row["bank_ref"] for row in w.bank}
    for m in w.matches:
        assert m["bank_ref"] in refs
        assert set(m["settlement_ids"]) <= settlements
        assert set(m["payment_ids"]) <= payments


def test_e07_only_flags_orders_claiming_paid(dataset):
    """An order with no payment and no claim to have been paid is a cart, not an exception."""
    w, injected, _ = dataset
    by_id = {o["order_id"]: o for o in w.orders}
    paid_for = {p["order_id"] for p in w.payments}
    for b in injected:
        if b["code"] == "E07":
            assert by_id[b["record_id"]]["status"] == "paid"
            assert b["record_id"] not in paid_for


def test_same_seed_is_byte_identical(tmp_path):
    """Acceptance 4 starts here: if the data moves, no delta between rungs means anything."""
    first, second = tmp_path / "a", tmp_path / "b"
    world.write(build_dataset("train")[0], first)
    world.write(build_dataset("train")[0], second)
    for name in world.FIELDS:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_seeds_produce_different_data():
    """Held-out has to actually be held out, not the same rows under another name."""
    train = {p["payment_id"] for p in world.build(SEEDS["train"]).payments}
    heldout = {p["payment_id"] for p in world.build(SEEDS["heldout"]).payments}
    assert not train & heldout


def test_written_csvs_are_all_integer_paise(tmp_path):
    """No decimal point may reach a money column. Formatting happens at render, not here."""
    w, _, _ = build_dataset("train")
    world.write(w, tmp_path)
    for name, fields in world.FIELDS.items():
        with (tmp_path / name).open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for field in (f for f in fields if f.endswith("_paise")):
                    int(row[field])


def test_structural_knobs_land_near_target(dataset):
    """The rung split is downstream of these two, so a silent drift here is a silent lie in EVAL."""
    w, _, key = dataset
    bundled = sum(1 for m in w.matches if len(m["settlement_ids"]) > 1)
    assert 4 <= bundled <= 14, f"{bundled} bundled credits -- R2 needs a population to work on"
    treatments = Counter(
        "absent" if not any(c.isdigit() for c in row["narration"]) else "present"
        for row in w.bank
    )
    assert treatments["present"] > treatments["absent"]


def test_every_decoy_ties_to_the_paisa_after_injection(dataset):
    """R2 spends no tolerance, so a decoy off by one paisa is not a weaker decoy, it is none:
    the solver would find a single answer and match it while the key still claimed E14."""
    w, _, key = dataset
    assert key["ambiguous"], "no decoy was built -- E14 has no data and can never be scored"
    for a in key["ambiguous"]:
        target = w.credit(a["bank_ref"])["credit_paise"]
        for subset in [a["true_subset"], *a["decoy_subsets"]]:
            assert sum(w.settlement(sid)["net_amount_paise"] for sid in subset) == target


def test_the_decoy_knobs_still_equal_r2s_own():
    """The generator restates R2's window and size instead of importing them, so that the
    tests above assert something rather than a variable equalling itself. The cost of that
    is two declarations of one parameter, and a parameter declared twice drifts -- which is
    exactly what happened when the window moved to 6 and the size to 5 and the generator's
    comment was left describing 5 and 4. This is the check that makes the drift loud."""
    assert world.DECOY_WINDOW_DAYS == ladder.R2_WINDOW_DAYS
    assert (world.DECOY_MIN, world.DECOY_MAX) == (ladder.R2_SIZE_MIN, ladder.R2_SIZE_MAX)


def test_a_decoy_is_a_different_subset_inside_r2s_own_window_and_size(dataset):
    """A decoy outside R2's filter is removed before the solver runs and tests nothing.

    Asserted against `ladder`'s constants, not the generator's own: checking the generator
    against itself passes whatever either one says."""
    w, _, _ = dataset
    for a in w.ambiguous:
        true_subset = set(a["true_subset"])
        for decoy in a["decoy_subsets"]:
            assert not true_subset & set(decoy), "the decoy is the true subset"
            assert ladder.R2_SIZE_MIN <= len(decoy) <= ladder.R2_SIZE_MAX
            day = max(w.settlement(sid)["_settled_on"] for sid in true_subset)
            for sid in decoy:
                span = abs((w.settlement(sid)["_settled_on"] - day).days)
                assert span <= ladder.R2_WINDOW_DAYS, f"{sid} is {span} days out"


def test_decoys_leave_no_fingerprint(dataset):
    """The construction is only worth having if a decoy reads as ordinary data.

    Ties are made by choosing payment contents, not by moving `adjustment_paise` -- the gap
    runs to lakhs and would show up instantly against the range real adjustments live in.
    Two things say it stayed honest: every payment is still priced in whole rupees, and no
    adjustment left the band the generator draws them from.
    """
    w, _, _ = dataset
    assert not [p for p in w.payments if p["amount_paise"] % 100], \
        "a payment is priced in paise -- that row marks its settlement as constructed"
    for s in w.settlements:
        assert abs(s["adjustment_paise"]) < 50_000, \
            f"{s['settlement_id']} carries a {s['adjustment_paise']} paise adjustment"


def test_the_clean_world_still_ties_with_decoys_in_it():
    """PRD 8's identity, unloosened. Payments added to close a gap carry their own fee and
    GST, so both sides of the equation move together or the construction is wrong."""
    world.assert_identity(world.build(SEEDS["train"]))
    world.assert_identity(world.build(SEEDS["heldout"]))


def test_a_decoy_is_built_only_from_settlements_that_survive_the_ladder(dataset):
    """The invariant the first decoy design was missing, and the reason it was inert.

    A rival subset has to still be open when R2 runs, or it is not a rival. A solo-credited
    settlement is claimed by R0 or R1 against its own credit long before the solver starts,
    so a decoy made of those dissolves and R2 sees one answer where the key claims two.
    Every decoy member must therefore sit inside another bundled credit, or in transit with
    no credit to be claimed against.
    """
    w, _, _ = dataset
    bundled = {sid for m in w.matches if len(m["settlement_ids"]) > 1
               for sid in m["settlement_ids"]}
    for a in w.ambiguous:
        own = set(a["true_subset"])
        for decoy in a["decoy_subsets"]:
            for sid in decoy:
                solo = (sid in w.credit_of_settlement) and sid not in bundled
                assert not solo, f"{sid} has its own credit -- R0/R1 will claim it first"
                assert sid not in own


def test_a_decoy_target_gives_up_its_utr(dataset):
    """PRD 5 lets R2 use a reference naming a settlement in one subset as evidence, and the
    narration carries a true-subset UTR. An ambiguity the evidence resolves is not one."""
    from match.ladder import _resembles, _tokens
    w, _, _ = dataset
    utr = {s["settlement_id"]: s["utr"] for s in w.settlements}
    for a in w.ambiguous:
        tokens = _tokens(w.credit(a["bank_ref"])["narration"])
        for subset in [a["true_subset"], *a["decoy_subsets"]]:
            named = [s for s in subset
                     if any(t == utr[s] or _resembles(t, utr[s]) for t in tokens)]
            assert not named, f"narration still names {named} -- the evidence resolves this"


def test_the_fill_leaves_the_host_inside_the_natural_spread(dataset):
    """A settlement that took a decoy's added payments must not stand out by volume."""
    from collections import Counter
    w, _, _ = dataset
    per = Counter(p["settlement_id"] for p in w.payments if p["settlement_id"])
    natural = sorted(per.values())
    for a in w.ambiguous:
        assert a["payments_added"] <= world.DECOY_FILL_MAX
        for sid in a["decoy_subsets"][0]:
            assert per[sid] <= natural[-1], f"{sid} holds more payments than any other"

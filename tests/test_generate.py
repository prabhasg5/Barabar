import csv
from collections import Counter

import pytest

from generate import world
from generate.__main__ import SEEDS, build_dataset

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

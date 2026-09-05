"""The render layer, against fixed inputs.

Two kinds of test here. Most are the primitives: data in, exact string out, no terminal
involved. The last two are the ones that matter -- they guard the two places where this
layer restates something the engine already knows, which is where a render layer normally
starts lying about the number it renders.
"""

import os
import re
from datetime import date
from pathlib import Path

import pytest

from tui.palette import Pen, pen as make_pen
from tui.primitives import (bps, bucket_meter, decimal_spine, hatched, level_bar,
                            level_line, show_bps)

PLAIN = Pen(colour=False, motion=False)
ROOT = Path(__file__).resolve().parents[1]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def flat(lines) -> list[str]:
    return [ANSI.sub("", line) for line in lines]


# --- the level bar -------------------------------------------------------------------------

def test_a_level_close_ends_both_bars_on_the_line():
    top, bottom, note = level_bar(1000, 1000, 10, PLAIN)
    assert top.endswith("██████████┊")
    assert bottom.endswith("██████████┊")
    assert "level" in note


def test_a_shortfall_draws_the_gap_and_names_it():
    top, bottom, note = level_bar(1000, 600, 10, PLAIN)
    assert top.endswith("██████████┊")
    assert bottom.endswith("██████▒▒▒▒┊")
    assert "₹4.00 short" in note


def test_a_shortfall_too_small_to_draw_still_draws_one_cell():
    """A break that rounds away to nothing reads as 'level'. It must never round away.

    This is the whole reason `_span` has a floor: 0.02% of a crore is Rs 2,000 and it would
    otherwise be zero cells of gap under a bar that looks finished.
    """
    _, bottom, note = level_bar(1000000, 999999, 10, PLAIN)
    assert "▒" in bottom
    assert "₹0.01 short" in note


def test_over_received_puts_the_line_before_the_end():
    top, bottom, note = level_bar(600, 1000, 10, PLAIN)
    assert top == "  expected  ██████┊"
    assert bottom.count("█") == 10
    assert "₹4.00 over" in note


def test_growing_the_received_bar_only_moves_the_lower_line():
    top, bottom, _ = level_bar(1000, 1000, 10, PLAIN, grown=0)
    assert top.endswith("██████████┊")
    assert "█" not in bottom


def test_level_line_marks_the_column():
    assert level_line(10, 4) == "    ┊"
    assert level_line(10, 99) == " " * 10 + "┊"


# --- the other primitives ------------------------------------------------------------------

def test_the_decimal_spine_aligns_the_decimal_point():
    lines = flat(decimal_spine([("a", 43218755, ""), ("b", 5, ""), ("c", -8641200, "")], PLAIN))
    columns = {line.index(".") for line in lines}
    assert len(columns) == 1, lines


def test_the_bucket_meter_itemises_and_never_totals():
    lines = flat(bucket_meter(
        [("reconciled", 90, "fill", ""), ("open", 10, "open", "")], 100, PLAIN, width=10))
    assert lines[0].count("█") == 9 and "90.00%" in lines[0]
    assert lines[1].count("▒") == 1 and "10.00%" in lines[1]
    assert not any("100" in line for line in lines)


def test_a_bucket_holding_money_never_draws_as_empty():
    lines = flat(bucket_meter([("tail", 1, "open", "")], 10000, PLAIN, width=10))
    assert lines[0].count("▒") == 1


def test_in_transit_is_a_texture_and_never_an_accent():
    """Nothing is wrong with in-transit money, so it may not wear the colour that means
    something is. Hatch carries it instead -- which also survives NO_COLOR."""
    assert hatched(3) == "▓▓▓"
    line = bucket_meter([("in transit", 5, "hatch", "")], 10, Pen(colour=True), width=10)[0]
    assert "▓" in line
    assert "38;2;184;107;10" not in line and "38;2;166;30;36" not in line


# --- ratios and the palette ----------------------------------------------------------------

@pytest.mark.parametrize("part, whole, expected", [
    (3514, 5000, 7028), (0, 100, 0), (1, 0, 0), (231, 5038, 459), (-5, 10, -5000)])
def test_bps_rounds_half_away_from_zero(part, whole, expected):
    assert bps(part, whole) == expected


def test_bps_is_the_same_function_the_harness_scores_with():
    """This layer cannot import eval/ -- the anti-circularity guard is a static scan for the
    name -- so `bps` is written out twice. Two copies of a rounding rule is exactly how a
    rendered percentage and a scored one drift apart, so the copies are compared here."""
    source = ROOT.joinpath("eval", "harness.py").read_text(encoding="utf-8")
    scope: dict = {}
    exec(source[source.index("def bps"):source.index("def show_bps")], scope)
    for part in range(0, 5039, 7):
        assert scope["bps"](part, 5038) == bps(part, 5038)


def test_show_bps_never_loses_a_hundredth():
    assert show_bps(8873) == "88.73%" and show_bps(10000) == "100.00%"
    assert show_bps(459) == "4.59%" and show_bps(0) == "0.00%"


def test_no_colour_means_no_escape_codes_anywhere():
    line = "".join(bucket_meter([("x", 1, "open", "note")], 2, PLAIN, width=4))
    assert "\x1b" not in line


@pytest.mark.parametrize("value, colour", [("0", False), ("1", False), ("", True)])
def test_no_color_is_read_the_way_the_convention_specifies(monkeypatch, value, colour):
    """Present and non-empty turns colour off. Both halves are traps in opposite directions.

    `NO_COLOR=0` must still disable colour -- reading the value as a boolean is exactly the
    mistake the convention exists to prevent -- and `NO_COLOR=` must leave it on, which is
    how a user unsets it for one command. The first version of this test set only "0" and so
    passed against both readings; it is parametrised because that is what made it useless.
    """
    class Tty:
        def isatty(self):
            return True
    monkeypatch.setenv("NO_COLOR", value)
    assert make_pen(stream=Tty()).colour is colour


def test_no_motion_is_a_separate_switch_from_colour(monkeypatch):
    class Tty:
        def isatty(self):
            return True
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert make_pen(stream=Tty()).colour and make_pen(stream=Tty()).motion
    assert make_pen(no_motion=True, stream=Tty()).colour
    assert not make_pen(no_motion=True, stream=Tty()).motion


def test_a_pipe_gets_neither_colour_nor_motion():
    class Pipe:
        def isatty(self):
            return False
    assert not make_pen(stream=Pipe()).colour and not make_pen(stream=Pipe()).motion


# --- the two places this layer restates the engine -----------------------------------------

def test_the_rendered_coverage_split_equals_the_scored_one():
    """`tui.coverage` and `eval/harness.py`'s `coverage_split` compute the same three buckets
    from the same run. One is what a merchant reads, the other is what gets scored, and a
    render layer quietly disagreeing with the scorer is the failure this file exists for."""
    import sys
    sys.path.insert(0, str(ROOT.joinpath("eval")))
    from exceptions import classify
    from harness import coverage_split
    from ingest.load import load
    from match.ladder import run
    from tui.__main__ import coverage

    folder = ROOT.joinpath("data", "heldout")
    if not folder.exists():
        pytest.skip("run: PYTHONPATH=src python -m generate heldout")
    ledger = load(folder)
    result = run(ledger)
    exceptions = classify(ledger, result)[0]
    mine, theirs = coverage(ledger, result, exceptions), coverage_split(ledger, result, exceptions)
    assert mine["reconciled"] == theirs["reconciled"]
    assert mine["in_transit"] == theirs["in_transit"]
    assert mine["still_open"] == theirs["still_open"]
    assert mine["by_code"] == theirs["by_code"]


def test_the_level_bar_gap_is_the_identity_residue():
    """The two sides of the close screen must be the same two sides the eval reports as
    `unexplained_paise` -- otherwise the picture and the number describe different runs.

    Compared against the harness rather than against a written-down figure. A pinned number
    would survive the next regeneration by describing the previous dataset, which is the
    failure the 2026-09-01 entries in DECISIONS.md are all instances of.

    It also pins the thing that made this screen possible: the in-transit slice is derived
    from the classifier's E12 rows, not read out of the answer key, and the assertion is
    that the two agree."""
    import json
    import sys
    sys.path.insert(0, str(ROOT.joinpath("eval")))
    from exceptions import classify
    from harness import check_conservation
    from ingest.load import load
    from match.ladder import run
    from tui.__main__ import sides

    folder = ROOT.joinpath("data", "heldout")
    key = ROOT.joinpath("eval", "ground_truth", "heldout.json")
    if not folder.exists() or not key.exists():
        pytest.skip("run: PYTHONPATH=src python -m generate heldout")
    ledger = load(folder)
    truth = json.loads(key.read_text(encoding="utf-8"))
    expected, received, in_transit = sides(ledger, classify(ledger, run(ledger))[0])
    assert in_transit == truth["totals"]["in_transit_paise"]
    assert expected - received == check_conservation(ledger, truth)


# --- the exception browser -----------------------------------------------------------------

import io

from tui.browse import (Screen, getkey, interactive, key_of, load_decisions, matches,
                        ordered, save_decisions, two_sides, weight)


class Row:
    """A stand-in for `exceptions.Exception_`, so these tests fix their own inputs rather
    than depending on whatever the classifier happened to emit this run."""

    def __init__(self, code, record_type="bank", record_id="B1", other_id="",
                 delta=0, rung="R2", reason="because."):
        self.code, self.record_type, self.record_id = code, record_type, record_id
        self.other_id, self.delta_paise, self.rung, self.reason = other_id, delta, rung, reason

    @property
    def is_break(self):
        return self.code != "E14"


DAY = date(2026, 3, 31)


class Book:
    orders = [{"order_id": "o1", "gross_amount_paise": 500000, "status": "paid"}]
    payments = [{"payment_id": "p1", "order_id": "o1", "amount_paise": 150900,
                 "method": "card", "fee_paise": 2233, "gst_paise": 402,
                 "settlement_id": "s1", "captured_at": DAY}]
    refunds = [{"refund_id": "r1", "payment_id": "", "amount_paise": 4000, "type": "refund"}]
    settlements = [{"settlement_id": "s1", "net_amount_paise": 900000, "utr": "U1",
                    "settled_at": DAY, "fee_paise": 0, "gst_paise": 0,
                    "refund_paise": 0, "adjustment_paise": 0}]
    bank = [{"bank_ref": "B1", "credit_paise": 283928, "narration": "N", "txn_date": DAY,
             "debit_paise": 0, "closing_balance_paise": 0}]


def test_weight_is_the_delta_wherever_there_is_one():
    assert weight(Row("E05", "payment", "p1", delta=-926), Book) == 926
    assert weight(Row("E02", "settlement", "s1", delta=-900000), Book) == 900000


def test_e14_is_weighted_by_the_credit_it_holds_not_by_its_zero_delta():
    """E14's delta is zero because nothing is at risk -- that is the code's whole meaning.
    Sorting on it would put the highest-leverage row in the run last."""
    assert weight(Row("E14", "bank", "B1", delta=0), Book) == 283928


def test_no_other_zero_delta_code_borrows_its_record_amount():
    """The version that fell back to the record amount for *every* zero-delta code sorted an
    E13 second in the whole list, on money that had already matched and was never at issue."""
    for code in ("E13", "E06", "E07", "E08", "E09", "E12"):
        assert weight(Row(code, "bank", "B1", delta=0), Book) == 0


def test_the_list_is_sorted_by_money_held_out_descending():
    rows = [Row("E05", "payment", "p1", delta=-926), Row("E14", "bank", "B1"),
            Row("E13", "bank", "B1"), Row("E02", "settlement", "s1", delta=-900000)]
    assert [e.code for e in ordered(rows, Book)] == ["E02", "E14", "E05", "E13"]


@pytest.mark.parametrize("flt, code, keep", [
    ("", "E05", True), ("E05", "E05", True), ("e05", "E05", True), ("E05", "E10", False),
    ("b", "E05", True), ("b", "E14", False), ("q", "E14", True), ("q", "E05", False)])
def test_the_filter_takes_a_code_or_the_break_question_split(flt, code, keep):
    assert matches(Row(code), flt) is keep


def test_the_arithmetic_for_a_fee_variance_shows_both_sides_and_the_subtraction():
    left, right, sums = two_sides(Row("E05", "payment", "p1", delta=926), Book, None)
    assert left[0] == "contracted" and right[0] == "billed"
    assert ("total", "₹35.61", True) in left[1]      # 200bps + 1800bps gst on Rs 1,509
    assert ("total", "₹26.35", True) in right[1]
    assert "₹26.35 billed − ₹35.61 contracted = ₹9.26 under" in sums[0]


def test_a_duplicate_marks_the_id_as_the_differing_field_never_the_amount():
    """The two rows agreeing on the amount is what makes one of them a duplicate. Painting
    the accent on the field that agrees points the reader at the wrong thing."""
    left, _, sums = two_sides(Row("E10", "payment", "p1", other_id="p1"), Book, None)
    differs = {field for field, _, d in left[1] if d}
    assert differs == {"payment id"}
    assert "only the id differs" in sums[0]


def test_arrow_keys_are_j_and_k_and_a_bare_escape_does_not_block():
    assert getkey(io.StringIO("j")) == "j"
    assert getkey(io.StringIO("\x1b[A")) == "k"
    assert getkey(io.StringIO("\x1b[B")) == "j"
    assert getkey(io.StringIO("\x1b")) == "\x1b"


def test_a_decision_round_trips_through_the_file(tmp_path, monkeypatch):
    import tui.browse as browse
    monkeypatch.setattr(browse, "DECISIONS", tmp_path.joinpath("decisions.json"))
    save_decisions({"E14:B1": {"decision": "kept open", "note": "asked ops"}})
    assert load_decisions()["E14:B1"]["note"] == "asked ops"


def test_a_corrupt_decisions_file_never_takes_the_browser_down(tmp_path, monkeypatch):
    """A reviewer's judgments are not engine output and must not be able to stop a run.
    An unreadable file reads as no decisions; the next write replaces it."""
    import tui.browse as browse
    bad = tmp_path.joinpath("decisions.json")
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(browse, "DECISIONS", bad)
    assert load_decisions() == {}


def test_decisions_are_written_by_rename_so_a_half_write_is_never_the_state(tmp_path,
                                                                           monkeypatch):
    import tui.browse as browse
    path = tmp_path.joinpath("decisions.json")
    monkeypatch.setattr(browse, "DECISIONS", path)
    save_decisions({"a": {"decision": "accepted"}})
    seen = []
    real = os.replace

    def watched(src, dst):
        seen.append((Path(src).name, Path(dst).name))
        return real(src, dst)

    monkeypatch.setattr(browse.os, "replace", watched)
    save_decisions({"a": {"decision": "accepted"}, "b": {"decision": "kept open"}})
    assert seen and seen[0][1] == "decisions.json"
    assert len(load_decisions()) == 2


def test_the_key_is_the_code_and_the_record_so_two_codes_on_one_record_stay_apart():
    assert key_of(Row("E13", "bank", "B1")) != key_of(Row("E01", "bank", "B1"))


class Tty:
    def isatty(self):
        return True


class Pipe:
    def isatty(self):
        return False


def test_no_motion_does_not_disable_the_exception_browser():
    """`--no-motion` suppresses the 400ms bar, not the ability to press a key.

    It used to do both, because `Screen.live` read `pen.motion`. Someone recording a demo
    without animation is exactly the person who still has to navigate 138 exceptions.

    **Asserted on `Screen` itself, not on `interactive`.** The first version of this test
    checked the helper, and the deliberate break -- putting `pen.motion and` back in front of
    the call -- passed it. A test that cannot see the bug it was written for is the same green
    tautology as `test_a_decoy_is_a_different_subset`.
    """
    from tui.palette import Pen
    assert Screen(Pen(colour=True, motion=False), Tty(), Tty()).live is True
    assert Screen(Pen(colour=True, motion=True), Tty(), Tty()).live is True
    assert Screen(Pen(colour=True, motion=True), Pipe(), Tty()).live is False


@pytest.mark.parametrize("stdin, stdout, live", [
    (Tty(), Tty(), True), (Pipe(), Tty(), False), (Tty(), Pipe(), False),
    (Pipe(), Pipe(), False)])
def test_both_streams_have_to_be_a_terminal(stdin, stdout, live):
    """Keys come from stdin; the alternate buffer and cursor moves go to stdout. A pipe on
    either end and the browser prints its list once instead."""
    assert interactive(stdin, stdout) is live

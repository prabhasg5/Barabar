"""The render layer, against fixed inputs.

Two kinds of test here. Most are the primitives: data in, exact string out, no terminal
involved. The last two are the ones that matter -- they guard the two places where this
layer restates something the engine already knows, which is where a render layer normally
starts lying about the number it renders.
"""

import re
from pathlib import Path

import pytest

from tui.palette import Pen, pen as make_pen
from tui.primitives import (bps, bucket_meter, decimal_spine, hatched, level_bar,
                            level_line, offset_row, show_bps)

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


def test_an_offset_row_is_misalignment_not_a_badge():
    row = ANSI.sub("", offset_row(600, 1000, 10, PLAIN))
    assert row == "██████▒▒▒▒┊"
    assert not any(c in row for c in "[]()•●○!")


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

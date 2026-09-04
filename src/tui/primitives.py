"""The element set from PRD 10, drawn in characters. Data in, styled lines out.

Every element here is the same idea at a different scale: **two sides that either line up or
they don't.** There is no chart in this module and there must never be one. If a new element
cannot be expressed as alignment or its absence, it does not belong.

Pure functions. Nothing here reads a file, prints, sleeps, or looks at a terminal -- which is
what lets the tests call them against fixed inputs and compare strings. The one moving thing
in the program (the received bar growing on load) is animation *over* `level_bar`, done by the
caller: it asks for the bar at a series of lengths and reprints. The primitive never moves.

Integer paise only, like everything else under src/. Proportions are `width * part // whole`.
"""

from money import Paise, format_rupees

FILL = "█"      # money accounted for
GAP = "▒"       # the finding -- the only coloured cell on a screen
HATCH = "▓"     # in transit: settled, not yet credited. Ink, never an accent.
LEVEL = "┊"     # the level line, where both sides must end


def bps(part: int, whole: int) -> int:
    """A ratio in basis points, half away from zero. The twin of eval/harness.py's `bps`.

    Written out rather than imported because nothing under src/ may reference that tree --
    it is where the answer key lives, and the anti-circularity guard is a static scan for
    the name. The rounding is identical and tests/test_tui.py asserts it stays identical.
    """
    if whole == 0:
        return 0
    sign = -1 if part < 0 else 1
    return sign * ((abs(part) * 1000000 + whole * 50) // (whole * 100))


def show_bps(rate: int) -> str:
    return f"{rate // 100}.{abs(rate) % 100:02d}%"


def _span(width: int, part: int, whole: int) -> int:
    """Cells for `part` of `whole`. Never rounds a non-zero amount away to nothing.

    A bucket holding real money that draws as zero cells reads as "none", and the bar is
    the only thing some readers will look at.
    """
    if whole <= 0 or part <= 0:
        return 0
    return max(1, width * part // whole)


def level_line(width: int, at: int) -> str:
    """A row of blanks with the level mark at `at`. The dashed line of PRD 10, one cell wide."""
    at = max(0, min(at, width))
    return " " * at + LEVEL


def level_bar(expected: int, received: int, width: int, pen,
              grown: int | None = None, labels: tuple[str, str] = ("expected", "received"),
              gutter: int = 10) -> list[str]:
    """Two bars, shared origin, and the gap between their right edges is the finding.

    `expected` is the ledger side for the period -- what the books say should have reached
    the bank by the time the statement closed. `received` is the bank credit. Money settled
    *after* the statement closed is not on this bar at all: it is neither expected in the
    period nor missing from it, and drawing it here would make a clock look like a break.
    It has its own bucket.

    A non-zero shortfall always draws at least one cell. A break that rounds away to nothing
    reads as "level", and the bar is the only thing some readers look at.

    `grown` is the animation hook: draw the received bar as if only that many paise had
    arrived. `None` means final length. The primitive does not animate; it draws one frame.
    """
    scale = max(expected, received, 1)
    end = _span(width, expected, scale)
    shown = received if grown is None else grown
    drawn = _span(width, shown, scale)
    got, over = min(drawn, end), max(0, drawn - end)
    short = end - got
    if shown < expected and not short:
        got, short = end - 1, 1        # a real shortfall never rounds away to a full bar


    top = FILL * end + LEVEL
    bottom = (FILL * (got + over) + pen.open(GAP * short)
              + " " * max(0, end - got - short) + (LEVEL if not over else ""))

    lines = [f"  {labels[0]:<{gutter}}{pen.ink(top)}",
             f"  {labels[1]:<{gutter}}{bottom}"]

    delta = expected - received
    if delta:
        word = "short" if delta > 0 else "over"
        amount = f"{format_rupees(Paise(abs(delta)))} {word}"
        lines.append(" " * max(0, gutter + 2 + end + 1 - len(amount)) + pen.open(amount))
    else:
        lines.append(" " * (gutter + 2) + pen.muted("level -- both sides end together"))
    return lines


def decimal_spine(rows: list[tuple[str, int, str]], pen, label_width: int = 22,
                  money_width: int = 18) -> list[str]:
    """Money right-aligned in a fixed column, so the decimals align down the whole page.

    `format_rupees` always ends in exactly two decimal places, so right-aligning the string
    aligns the point -- no separate decimal-position arithmetic, and none that could drift
    out of agreement with the formatter.
    """
    out = []
    for label, amount, note in rows:
        money = format_rupees(Paise(amount))
        out.append(f"  {label:<{label_width}}{money:>{money_width}}"
                   + (f"   {pen.muted(note)}" if note else ""))
    return out


def bucket_meter(buckets: list[tuple[str, int, str, str]], total: int, pen,
                 width: int = 26, label_width: int = 13) -> list[str]:
    """One small level bar per bucket, showing its share. Itemised, never totalled.

    `buckets` is (label, count, tone, note); tone picks the glyph and the ink. Reconciled is
    plain fill, in transit is hatched, still open is the accent -- the same three states the
    close screen shows at period scale, which is the point of reusing the element.
    """
    glyph = {"fill": FILL, "hatch": HATCH, "open": GAP}
    paint = {"fill": pen.ink, "hatch": pen.rule, "open": pen.open}
    out = []
    for label, count, tone, note in buckets:
        cells = _span(width, count, total)
        bar = paint[tone](glyph[tone] * cells)
        out.append(f"  {label:<{label_width}}{bar}{' ' * (width - cells)}"
                   f"{show_bps(bps(count, total)):>8}{count:>7}   {pen.muted(note)}")
    return out


def offset_row(received: int, expected: int, width: int, pen, at_risk: bool = False) -> str:
    """One exception as misalignment: a bar that stops short of the level line. No badge.

    This is the list row's version of the level bar, and the reason the exceptions list has
    a ragged right edge that says how the month went before a number is read.
    """
    scale = max(expected, received, 1)
    got = _span(width, received, scale)
    short = max(0, _span(width, expected, scale) - got)
    ink = pen.risk if at_risk else pen.open
    return FILL * got + ink(GAP * short) + " " * (width - got - short) + LEVEL


def hatched(cells: int) -> str:
    """In transit. A texture, not a colour -- nothing is wrong with this money."""
    return HATCH * max(0, cells)

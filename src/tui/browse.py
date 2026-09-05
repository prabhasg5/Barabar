"""The exception list and the one exception opened. The working screen and the trusted one.

Two decisions in here that the brief asked to be argued rather than assumed, both settled by
what the data actually looks like rather than by taste:

**The list opens on everything, not on breaks alone.** The case for breaks-first is real -- a
controller's first question is what is wrong, not what is unanswered, and PRD 6 says burying a
question inside a pile of problems wastes the attention the pile needs. But a default filter is
*invisible state*, and a reader who does not notice it believes they have seen everything. That
is the same class of error as a silent row drop, which is the one failure this tool exists to
refuse. The separation PRD 6 asks for is done by the header, which counts and prices breaks and
questions apart, and by `/`, which is one keystroke and leaves a visible mark when it is on.

**`r` opens the detail positioned on the review prompt.** It is a shortcut into the same screen,
never a second way to decide. A decision made from the list is a decision made on a code chip
and a rupee figure, and "keep open" requires a note -- a note written without the arithmetic in
front of you is a worse note. So the answer to what `r` does that Enter does not is: it skips
the reading. It cannot skip the evidence.

No floats: this module is under src/ and the no-float scan covers it.
"""

import io
import json
import os
import select
import sys
import termios
import tty
from pathlib import Path

from money import Paise, format_rupees

ROOT = Path(__file__).resolve().parents[2]
# Deliberately not eval/results.json. That file is what the engine measured; this one is what a
# person decided, and a reviewer's judgment is not engine output. Mixing them would make a
# rerun either clobber the judgments or inherit them as if they were measurements.
DECISIONS = ROOT.joinpath("decisions.json")

ROW_BUDGET = 8          # header, footer and prompt; the rest of the 24 rows are exceptions
DETAIL_BAR = 34

# The one code whose `delta_paise` is not what it is holding, and the ledger field that is.
#
# E14 carries a delta of zero because nothing is at risk in an ambiguity -- that is the code's
# meaning rather than an omission. But the credit underneath it is unreconciled and is holding
# up the close: on held-out a single E14 holds 4.58 coverage points, more than any one break
# moves. Sorting it on its zero puts the highest-leverage row in the run underneath 96 fee
# variances of a few rupees each, and a list whose first promise is "biggest money first" would
# be lying in its first row.
#
# **Every other zero-delta code is genuinely holding nothing out**, which is why this table has
# one entry and not seven. E13 is an unreadable narration on a credit that *matched*; E06 to
# E09 are cut trails with the money sitting where it should. An earlier version fell back to
# the record's own amount for all of them and sorted an E13 second in the whole list, on
# ₹2,44,805 that was never at issue -- "the amount on the record" and "the amount at stake" are
# different quantities, and only the second one can be summed in a header.
#
# The figure above is coverage *points* (the delta 88.73% → 93.31%), not E14's 4.59% share of
# payments. They are two quantities one digit apart and conflating them is how this number
# drifted once already; see ARCHITECTURE.md §8.
HELD_BY_ITS_RECORD = {"E14": "credit_paise"}


# --- what a row is worth -------------------------------------------------------------------

def weight(e, ledger) -> int:
    """The money this row keeps out of a clean close. PRD 9.2's "rupee impact", made precise.

    `abs(delta_paise)` for every code but the one in `HELD_BY_ITS_RECORD`, where the reasoning
    lives. `delta_paise` is never rewritten -- this is a render-side ordering.
    """
    if int(e.delta_paise):
        return abs(int(e.delta_paise))
    field = HELD_BY_ITS_RECORD.get(e.code)
    if not field:
        return 0
    row = find(e.record_type, e.record_id, ledger)
    return abs(int(row[field])) if row and field in row else 0


def find(record_type: str, record_id: str, ledger):
    """The ledger row an exception points at. `record_type` is the classifier's own word."""
    where = {"bank": (ledger.bank, "bank_ref"),
             "settlement": (ledger.settlements, "settlement_id"),
             "payment": (ledger.payments, "payment_id"),
             "order": (ledger.orders, "order_id"),
             "refund": (ledger.refunds, "refund_id")}.get(record_type)
    if not where:
        return None
    rows, key = where
    return next((r for r in rows if r[key] == record_id), None)


def ordered(exceptions, ledger) -> list:
    """Biggest money first. Stable, so equal weights keep the classifier's order."""
    return sorted(exceptions, key=lambda e: -weight(e, ledger))


# --- decisions -----------------------------------------------------------------------------

def key_of(e) -> str:
    # ponytail: code + record id. Two datasets sharing a record id would share a decision;
    # add the dataset name here if that ever stops being hypothetical.
    return f"{e.code}:{e.record_id}"


def load_decisions() -> dict:
    if not DECISIONS.exists():
        return {}
    try:
        return json.loads(DECISIONS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_decisions(decisions: dict) -> None:
    """Write, then rename. A half-written decisions file must never be the state on disk."""
    tmp = DECISIONS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, DECISIONS)


# --- keys ----------------------------------------------------------------------------------

ARROWS = {"[A": "k", "[B": "j", "[C": "\r", "[D": "\x1b"}


def getkey(stream=None) -> str:
    """One keypress, with the arrows mapped onto j/k so both hands work.

    A bare Escape must not block waiting for the rest of a sequence that is never coming, so
    the two follow-on bytes are only read if they are already waiting. `select` with a timeout
    of 0 is a poll -- an integer, which keeps this module inside the no-float scan.
    """
    stream = stream or sys.stdin
    ch = stream.read(1)
    if ch != "\x1b":
        return ch
    try:
        ready = bool(select.select([stream], [], [], 0)[0])
    except (OSError, ValueError, io.UnsupportedOperation):
        ready = True          # not a real descriptor: a test stream. Read what is there.
    if not ready:
        return "\x1b"
    return ARROWS.get(stream.read(2), "\x1b")


def interactive(stdin=None, stdout=None) -> bool:
    """Whether there is a person at a terminal to press a key and watch a redraw.

    **Both streams, and nothing else.** This used to read `pen.motion`, which meant
    `--no-motion` silently turned the exception browser into a print-once list -- and someone
    recording a demo without the 400ms bar animation is exactly the person who still needs to
    navigate 138 exceptions. Motion is whether a thing moves; this is whether anyone is there.

    Both streams matter and for different reasons: keys are read from stdin, and the alternate
    buffer and cursor moves are written to stdout. A pipe on either end makes the browser print
    its list once, which is what the piped demo in the README does.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    return bool(getattr(stdin, "isatty", None) and stdin.isatty()
                and getattr(stdout, "isatty", None) and stdout.isatty())


class Screen:
    """Raw mode, the alternate buffer, and putting both back however we leave.

    The alternate buffer is why `q` returns the reader to the close summary they came from
    rather than to a screen the browser scrolled away.
    """

    def __init__(self, pen, stdin=None, stdout=None):
        self.pen = pen
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        # Deliberately not `pen.motion and ...`. See `interactive`.
        self.live = interactive(self.stdin, self.stdout)
        self.saved = None

    def __enter__(self):
        if self.live:
            self.saved = termios.tcgetattr(self.stdin.fileno())
            tty.setcbreak(self.stdin.fileno())
            print("\x1b[?1049h", end="")
        return self

    def __exit__(self, *_):
        if self.live:
            termios.tcsetattr(self.stdin.fileno(), termios.TCSADRAIN, self.saved)
            print("\x1b[?1049l", end="", flush=True)

    def draw(self, lines: list[str]) -> None:
        print(("\x1b[H\x1b[2J" if self.live else "") + "\n".join(lines), flush=True)

    def line(self, prompt: str) -> str:
        """A typed answer. Cooked mode for the duration, so the terminal edits the line."""
        if not self.live:
            return ""
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved)
        try:
            return input(prompt).strip()
        except EOFError:
            return ""
        finally:
            tty.setcbreak(sys.stdin.fileno())


# --- the list ------------------------------------------------------------------------------

def clip(text: str, room: int) -> str:
    return text if len(text) <= room else text[:room - 1] + "…"


def matches(e, flt: str) -> bool:
    if not flt:
        return True
    if flt in ("b", "breaks"):
        return e.is_break
    if flt in ("q", "questions"):
        return not e.is_break
    return e.code.upper() == flt.upper()


def list_lines(state) -> list[str]:
    pen, ledger = state["pen"], state["ledger"]
    shown = [e for e in state["rows"] if matches(e, state["filter"])]
    breaks = [e for e in shown if e.is_break]
    questions = [e for e in shown if not e.is_break]
    decided = state["decisions"]

    money = lambda rows: format_rupees(Paise(sum(weight(e, ledger) for e in rows)))
    out = [
        "  " + pen.ink("EXCEPTIONS") + "   "
        + pen.risk(f"{len(breaks)} breaks") + pen.muted(" · ") + money(breaks)
        + pen.muted("     ") + pen.open(f"{len(questions)} "
                                        f"{'question' if len(questions) == 1 else 'questions'}")
        + pen.muted(" · ") + money(questions),
        "  " + pen.muted("₹ = money held out of the close · a break is wrong, a question "
                         "is undecided"),
    ]
    out.append("  " + pen.rule("─" * 78))

    height = max(4, state["height"] - ROW_BUDGET)
    top = max(0, min(state["cursor"] - height + 1, len(shown) - height))
    top = max(0, top)
    for n, e in enumerate(shown[top:top + height], start=top):
        here = n == state["cursor"]
        tone = pen.open if not e.is_break else pen.ink
        mark = key_of(e) in decided
        row = (f"{'▸' if here else ' '} {e.code}  "
               f"{format_rupees(Paise(weight(e, ledger))):>14}  "
               f"{clip(e.reason.split('. ')[0], 44):<44}  {e.rung:<3}"
               f"{'✓' if mark else ' '}")
        out.append("  " + (pen.open(row) if here else tone(row)))
    if not shown:
        out.append("  " + pen.muted("Nothing matches that filter. `/` then enter clears it."))

    out.append("  " + pen.rule("─" * 78))
    where = f"{state['cursor'] + 1} of {len(shown)}" if shown else "0 of 0"
    flt = f"  [{clip(state['filter'], 8)}]" if state["filter"] else ""
    out.append("  " + pen.muted(f"j/k move · enter open · r review · / filter · q quit"
                                f"        {where}") + pen.open(flt))
    return out


# --- the detail ----------------------------------------------------------------------------

def two_sides(e, ledger, result) -> tuple:
    """Both sides of the mismatch, and the arithmetic between them.

    Returns `(left, right, sums)` where each side is `(title, [(field, value, differs)])`.
    Aligning on the field that differs is the whole point of the screen: a controller has to
    see *which* number disagrees, not be told that two records disagree.
    """
    row = find(e.record_type, e.record_id, ledger)
    other = find("settlement", e.other_id, ledger) if e.other_id else None
    rupees = lambda v: format_rupees(Paise(int(v)))

    if e.code in ("E03", "E04") and row:
        sid = e.other_id or next((m.settlement_ids[0] for m in result.matches
                                  if m.bank_ref == e.record_id), "")
        s = find("settlement", sid, ledger)
        left = (f"bank credit {e.record_id}", [
            ("date", f"{row['txn_date']:%d %b %Y}", False),
            ("narration", clip(row["narration"], 34), False),
            ("credit", rupees(row["credit_paise"]), True)])
        right = (f"settlement {sid}" if s else "no settlement ties to it", [
            ("settled", f"{s['settled_at']:%d %b %Y}" if s else "—", False),
            ("utr", s["utr"] if s else "—", False),
            ("net", rupees(s["net_amount_paise"]) if s else "—", True)])
        if s:
            delta = row["credit_paise"] - s["net_amount_paise"]
            sums = [f"{rupees(row['credit_paise'])} received "
                    f"{'−' if delta > 0 else '+'} {rupees(abs(delta))} "
                    f"= {rupees(s['net_amount_paise'])} settled",
                    f"the credit is {rupees(abs(delta))} "
                    f"{'over' if delta > 0 else 'short'} of the batch it names"]
        else:
            sums = [f"{rupees(row['credit_paise'])} arrived and no settlement or combination "
                    f"ties to it within tolerance"]
        return left, right, sums

    if e.code == "E05" and row:
        from audit.fees import expected_of
        fee, gst = expected_of(row["amount_paise"], row["method"])
        actual = row["fee_paise"] + row["gst_paise"]
        left = ("contracted", [
            ("method", row["method"], False),
            ("fee", rupees(fee), True),
            ("gst on fee", rupees(gst), True),
            ("total", rupees(int(fee) + int(gst)), True)])
        right = ("billed", [
            ("method", row["method"], False),
            ("fee", rupees(row["fee_paise"]), True),
            ("gst on fee", rupees(row["gst_paise"]), True),
            ("total", rupees(actual), True)])
        delta = actual - int(fee) - int(gst)
        return left, right, [
            f"{rupees(actual)} billed − {rupees(int(fee) + int(gst))} contracted "
            f"= {rupees(abs(delta))} {'over' if delta > 0 else 'under'}",
            f"on a {rupees(row['amount_paise'])} {row['method']} payment"]

    if e.code == "E10" and row:
        # The differing field is the id, and *only* the id -- that is the finding. Marking
        # the amount would paint the accent on the thing that agrees, which is backwards:
        # these two rows being identical is exactly what makes one of them a duplicate.
        twin = find("payment", e.other_id, ledger)
        make = lambda p, n: (f"capture {n}", [
            ("payment id", p["payment_id"], True),
            ("captured", f"{p['captured_at']:%d %b %Y}", False),
            ("order", p["order_id"], False),
            ("amount", rupees(p["amount_paise"]), False),
            ("settlement", p["settlement_id"] or "—", False)])
        return make(row, 1), (make(twin, 2) if twin else ("", [])), [
            f"identical in order and amount, and only the id differs -- "
            f"{rupees(row['amount_paise'])} was captured twice",
            "the ledger does not say which one is the duplicate, so both are named"]

    if e.code == "E02" and row:
        return (f"settlement {e.record_id}", [
            ("settled", f"{row['settled_at']:%d %b %Y}", False),
            ("utr", row["utr"], False),
            ("net", rupees(row["net_amount_paise"]), True)]), \
            ("bank credit", [("—", "nothing arrived", True)]), \
            [f"{rupees(row['net_amount_paise'])} settled and never reached the bank"]

    if e.code == "E14" and row:
        # No right-hand side, on purpose. The two sides of an ambiguity are the candidate
        # subsets, and they get the stack below -- where they can be seen to be identical,
        # which is the whole finding. A second column here would have to pick one to show.
        return (f"bank credit {e.record_id}", [
            ("date", f"{row['txn_date']:%d %b %Y}", False),
            ("narration", clip(row["narration"], 22), False),
            ("credit", rupees(row["credit_paise"]), False)]), ("", []), []

    if row:
        return (f"{e.record_type} {e.record_id}", [
            (k.replace("_paise", "").replace("_", " "),
             clip(rupees(v) if k.endswith("_paise") else str(v), 22), False)
            for k, v in list(row.items())[:5]]), ("", []), []
    return ((f"{e.record_type} {e.record_id}", []), ("", []), [])


def detail_lines(state) -> list[str]:
    pen, ledger, result = state["pen"], state["ledger"], state["result"]
    e = [x for x in state["rows"] if matches(x, state["filter"])][state["cursor"]]
    decided = state["decisions"].get(key_of(e))

    out = ["  " + pen.ink(e.code) + "  "
           + (pen.risk("break -- money is wrong") if e.is_break
              else pen.open("question -- money is fine, a decision is outstanding")),
           "  " + pen.rule("─" * 78)]
    for line in wrap_to(e.reason, 76):
        out.append("  " + line)
    out.append("")

    left, right, sums = two_sides(e, ledger, result)
    out.append("  " + pen.muted(f"{left[0]:<38}{right[0]}"))
    for n in range(max(len(left[1]), len(right[1]))):
        a = left[1][n] if n < len(left[1]) else ("", "", False)
        b = right[1][n] if n < len(right[1]) else ("", "", False)
        cell = lambda f, v, d: (pen.open if d else pen.ink)(f"{f:<12}{v:>24}")
        out.append("  " + cell(*a) + "  " + (cell(*b) if b[0] else ""))
    if sums:
        out.append("")
    for line in sums:
        for wrapped in wrap_to(line, 76):
            out.append("  " + pen.ink(wrapped))

    if e.code == "E14":
        out.append("")
        # The candidate stack: the same level bar, once per subset, all ending on the same
        # line. They are identical because they all tie exactly -- and seeing them line up is
        # the argument for refusing. There is nothing here to choose between.
        credit = find("bank", e.record_id, ledger)
        for a in result.ambiguous:
            if a.bank_ref != e.record_id:
                continue
            out.append("  " + pen.muted(f"{len(a.candidates)} combinations, every one of "
                                        f"them tying to the credit exactly"))
            for n, subset in enumerate(a.candidates, 1):
                parts = [find("settlement", sid, ledger) for sid in subset]
                total = sum(p["net_amount_paise"] for p in parts)
                out.append("  " + pen.ink(f"{n}  " + "█" * DETAIL_BAR + "┊")
                           + f"{format_rupees(Paise(total)):>15}")
                for sid, part in zip(subset, parts):
                    out.append("     " + pen.muted(
                        f"{sid:<24}{format_rupees(Paise(part['net_amount_paise'])):>13}"
                        f"   settled {part['settled_at']:%d %b}"))
        if credit:
            for line in wrap_to(f"The credit is "
                                f"{format_rupees(Paise(credit['credit_paise']))}. Both tie. "
                                f"Nothing chooses between them, so the engine did not -- "
                                f"picking one would be a guess wearing the costume of logic.",
                                72):
                out.append("     " + pen.open(line))

    trail = result.trail.get(e.record_id, [])
    if trail:
        out.append("")
        out.append("  " + pen.muted("what each rung tried"))
        for note in trail:
            for n, line in enumerate(wrap_to(note, 72)):
                out.append("    " + (pen.ink(line) if not n else pen.muted(line)))
    for p in result.proposals:
        if p.bank_ref == e.record_id and p.explanation:
            out.append("")
            out.append("  " + pen.muted(f"the model said, at confidence {p.confidence} "
                                        f"({p.provider}) -- recorded, never acted on"))
            for line in wrap_to(p.explanation, 72):
                out.append("    " + pen.muted(line))

    return out


def detail_frame(state) -> list[str]:
    """The detail, scrolled to fit. A 34-line E14 must stay readable in an 80x24 recording,
    and the alternative -- trimming the evidence to fit -- is the one thing this screen
    cannot do, since being the screen that shows all of it is its entire job."""
    pen = state["pen"]
    e = [x for x in state["rows"] if matches(x, state["filter"])][state["cursor"]]
    decided = state["decisions"].get(key_of(e))
    body = detail_lines(state)
    room = max(4, state["height"] - 4)
    state["scroll"] = max(0, min(state["scroll"], len(body) - room))
    more = len(body) - state["scroll"] - room
    out = body[state["scroll"]:state["scroll"] + room]
    out.append("  " + pen.rule("─" * 78))
    if decided:
        out.append("  " + pen.ink(f"reviewed: {decided['decision']}")
                   + pen.muted(f"   {decided['note']}" if decided.get("note") else ""))
    out.append("  " + pen.muted("a accept · o keep open · j/k scroll · q back")
               + (pen.open(f"   {more} more ↓") if more > 0 else ""))
    return out


def wrap_to(text: str, room: int) -> list[str]:
    import textwrap
    return textwrap.wrap(" ".join(text.split()), room) or [""]


# --- the loop ------------------------------------------------------------------------------

def browse(ledger, result, exceptions, pen, height: int = 24) -> dict:
    """The list, the detail, and the decisions they produce. Returns what was decided."""
    state = {"pen": pen, "ledger": ledger, "result": result,
             "rows": ordered(exceptions, ledger), "cursor": 0, "filter": "",
             "decisions": load_decisions(), "height": height, "scroll": 0}

    with Screen(pen) as screen:
        if not screen.live:
            screen.draw(list_lines(state))
            return state["decisions"]
        view = "list"
        while True:
            shown = [e for e in state["rows"] if matches(e, state["filter"])]
            state["cursor"] = max(0, min(state["cursor"], len(shown) - 1))
            screen.draw(list_lines(state) if view == "list" else detail_frame(state))
            key = getkey(self.stdin)

            if key in ("q", "\x1b", "\x03"):
                if view == "detail":
                    view = "list"
                    continue
                return state["decisions"]
            if key == "j":
                if view == "detail":
                    state["scroll"] += 1
                else:
                    state["cursor"] += 1
            elif key == "k":
                if view == "detail":
                    state["scroll"] = max(0, state["scroll"] - 1)
                else:
                    state["cursor"] -= 1
            elif key == "/" and view == "list":
                state["filter"] = screen.line("  filter (a code, b for breaks, "
                                              "q for questions, empty clears) > ")
                state["cursor"] = 0
            elif key in ("\r", "\n") and shown:
                view, state["scroll"] = "detail", 0
            elif key == "r" and shown:
                # Not a second way to decide -- the same screen, scrolled to the prompt.
                view = "detail"
                state["scroll"] = max(0, len(detail_lines(state)) - state["height"] + 4)
            elif view == "detail" and key in ("a", "o") and shown:
                e = shown[state["cursor"]]
                note = screen.line("  note > ") if key == "o" else screen.line(
                    "  note (optional) > ")
                if key == "o" and not note:
                    continue          # keeping it open without saying why is not a decision
                state["decisions"][key_of(e)] = {
                    "code": e.code, "record_id": e.record_id,
                    "decision": "accepted" if key == "a" else "kept open",
                    "note": note, "delta_paise": int(e.delta_paise), "rung": e.rung}
                save_decisions(state["decisions"])
                view = "list"
    return state["decisions"]

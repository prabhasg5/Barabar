"""PRD 10's six values, rendered for a terminal. Colour only ever means money state.

Three departures from the web palette, all forced by the medium and none of them a seventh
value:

  * **`--paper` is never emitted.** The ground belongs to the user's terminal. Painting a
    background over it fights their theme and leaves a rectangle of cream in a screenshot.
  * **`--ink` is the default foreground, not #14161A.** Ink is "text and matched figures",
    which is to say the monochrome state -- and a monochrome state has to be legible on a
    light terminal and a dark one. #14161A on a dark ground is invisible; the terminal's own
    foreground is correct on both by construction.
  * **`--rule` is dim rather than #DEDEDA.** A hairline must sit *under* the text. #DEDEDA
    is under ink on paper and over it on a dark ground, which inverts the hierarchy exactly
    where a screen recording would show it. Dim is the terminal's own word for the same role.

`--muted`, `--open` and `--risk` are emitted verbatim as truecolour. They carry meaning, and
per PRD 10's quality floor colour is never the sole carrier: every coloured state in this
program also has a word next to it.
"""

import os
import sys

MUTED = (110, 113, 120)      # --muted  #6E7178
OPEN = (184, 107, 10)        # --open   #B86B0A  ochre, needs review
RISK = (166, 30, 36)         # --risk   #A61E24  money confirmed lost or at risk

RESET = "\x1b[0m"
DIM = "\x1b[2m"


def _fg(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m"


class Pen:
    """Applies the palette, or does not. One object so a caller cannot half-honour NO_COLOR.

    `colour` and `motion` are separate switches because they answer to different people:
    NO_COLOR is a convention for pipes and colour-blind users, --no-motion is for a recording
    that must not have a moving frame in it. A pipe gets neither, because neither survives.
    """

    def __init__(self, colour: bool = True, motion: bool = True):
        self.colour = colour
        self.motion = motion

    def _wrap(self, code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if self.colour else text

    def ink(self, text: str) -> str:
        return text                                   # the terminal's own foreground

    def rule(self, text: str) -> str:
        return self._wrap(DIM, text)

    def muted(self, text: str) -> str:
        return self._wrap(_fg(MUTED), text)

    def open(self, text: str) -> str:
        return self._wrap(_fg(OPEN), text)

    def risk(self, text: str) -> str:
        return self._wrap(_fg(RISK), text)


def pen(no_motion: bool = False, stream=None) -> Pen:
    """The pen this run gets. NO_COLOR, --no-motion, and "am I even a terminal".

    NO_COLOR is read the way no-color.org specifies and not the way it looks: colour is off
    when the variable is present **and not empty**. Both halves are traps in opposite
    directions. `NO_COLOR=0` must still turn colour off -- reading the value as a boolean is
    the mistake the convention exists to prevent -- and `NO_COLOR=` must leave it on, which
    is how a user unsets it for one command without unsetting it for the shell.
    """
    stream = stream or sys.stdout
    tty = bool(getattr(stream, "isatty", None) and stream.isatty())
    return Pen(
        colour=tty and not os.environ.get("NO_COLOR"),
        motion=tty and not no_motion,
    )

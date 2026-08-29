"""Money primitives. Integer paise everywhere; rupees exist only at the render boundary.

Nothing in this module produces a float. See tests/test_money.py::test_no_floats_in_src,
which parses every module under src/ and fails on float literals, true division, and
calls to float()/round(). Do not weaken it.
"""

from typing import NewType

Paise = NewType("Paise", int)

RUPEE = "₹"


def mul_bps(amount: Paise, bps: int) -> Paise:
    """Multiply by a rate in basis points, rounding half away from zero.

    `bps` is an integer: 200 is 2%, 1800 is 18%. Rates never enter this codebase as
    floats -- 0.02 in a money path is the bug the no-float test exists to catch.

    Half rounds away from zero, so a fee and its reversal are equal and opposite:
    25 paise at 2% is 0.5 paise, which bills as 1, and refunds as 1.

    Sign is handled explicitly because `//` floors: (-100 * 200 + 5000) // 10000 is 0,
    not -2, which would silently under-refund every negative amount in the book.
    """
    sign = -1 if amount < 0 else 1
    return Paise(sign * ((abs(amount) * bps + 5000) // 10000))


def format_rupees(amount: Paise) -> str:
    """Render paise as rupees with Indian digit grouping: 43218755 -> '₹4,32,187.55'.

    Not `{:,}`, which groups in thousands and gives 432,187 where a merchant reads 4,32,187.
    """
    rupees, paise = divmod(abs(amount), 100)
    sign = "-" if amount < 0 else ""
    return f"{sign}{RUPEE}{_group(rupees)}.{paise:02d}"


def _group(rupees: int) -> str:
    """Indian grouping: last three digits, then pairs. 6842100 -> '68,42,100'."""
    digits = str(rupees)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = [head[max(i - 2, 0):i] for i in range(len(head), 0, -2)]
    return ",".join(reversed(pairs)) + "," + tail

import ast
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from money import Paise, format_rupees, mul_bps

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT.joinpath("src")
# eval/ handles paise too -- the scan covers it for the same reason it covers src/.
SCANNED = (SRC, ROOT.joinpath("eval"))


@pytest.mark.parametrize(
    "amount, bps, expected",
    [
        (0, 200, 0),
        (100, 200, 2),           # Rs 1 at 2%
        (2500, 1800, 450),
        (25, 200, 1),            # exactly half a paisa, rounds away from zero
        (25, 199, 0),            # just under half
        (-25, 200, -1),          # the floor bug: naive // gives 0 here
        (-100, 200, -2),
        (43218755, 200, 864375),
    ],
)
def test_mul_bps(amount, bps, expected):
    assert mul_bps(Paise(amount), bps) == expected


@pytest.mark.parametrize(
    "amount, expected",
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (100, "₹1.00"),
        (100000, "₹1,000.00"),
        (4321875, "₹43,218.75"),
        (43218755, "₹4,32,187.55"),
        (684210000, "₹68,42,100.00"),
        (1000000000, "₹1,00,00,000.00"),   # one crore rupees
        (-8641200, "-₹86,412.00"),
    ],
)
def test_format_rupees(amount, expected):
    assert format_rupees(Paise(amount)) == expected


@given(st.integers(min_value=0, max_value=10**12), st.integers(min_value=0, max_value=10000))
def test_mul_bps_is_sign_symmetric(amount, bps):
    """A fee and its reversal must be equal and opposite, or refunds invent money."""
    assert mul_bps(Paise(-amount), bps) == -mul_bps(Paise(amount), bps)


@given(st.integers(min_value=-10**14, max_value=10**14))
def test_format_rupees_round_trips(amount):
    """Rendering must be lossless -- a display helper that drops paise is the whole risk."""
    rendered = format_rupees(Paise(amount))
    rupees, _, paise = rendered.lstrip("-₹").partition(".")
    parsed = int(rupees.replace(",", "")) * 100 + int(paise)
    assert (-parsed if rendered.startswith("-") else parsed) == amount


def test_no_floats_in_src():
    """Hard rule 1: no float may exist in a money path.

    Static, not isinstance checks -- the likeliest way a float appears is a formatting
    helper doing paise / 100, which no runtime assertion on inputs would ever see.
    """
    offences = []
    for path in sorted(q for root in SCANNED for q in root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                bad = f"float literal {node.value!r}"
            elif isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Div):
                bad = "true division (/) -- use // or divmod"
            elif isinstance(node, ast.Name) and node.id == "float":
                bad = "the name `float` (call, annotation, or isinstance check)"
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "round":
                bad = "call to round() -- rounding goes through mul_bps"
            else:
                continue
            offences.append(f"{path.relative_to(ROOT)}:{node.lineno}: {bad}")
    assert not offences, "floats in money paths:\n" + "\n".join(offences)

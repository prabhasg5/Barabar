"""Read the five CSVs, normalise dates and money, refuse anything unreadable.

Two lines this module holds:

  * It rejects rows it cannot *read*. It never rejects a row that merely looks wrong --
    a payment with no order, a refund with no payment, a payment in no settlement batch.
    Those are E06, E08/E09 and E02, which is to say they are the findings the tool exists
    to produce. Dropping them at the door would leave a clean-looking close and no answer.
  * It reports every bad row at once and then loads nothing. A reconciliation that quietly
    proceeds on 4,998 of 5,000 rows produces a confident close that is wrong by two rows,
    which is the exact failure this tool is meant to prevent.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from money import Paise

DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%b-%y", "%Y-%m-%d %H:%M:%S")
DATE_HELP = "DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YY or YYYY-MM-DD HH:MM:SS"
METHODS = ("upi", "card", "netbanking", "wallet")
REFUND_TYPES = ("refund", "chargeback")


class IngestError(Exception):
    """Carries every problem found, not the first one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def text(value: str) -> str:
    return value.strip()


def ident(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("is empty")
    return value


def optional_ident(value: str) -> str:
    """Blank is allowed and meaningful: it is what an orphan record looks like."""
    return value.strip()


def day(value: str):
    value = value.strip()
    if not value:
        raise ValueError("is empty")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"is not a date I recognise (expected {DATE_HELP})")


def paise(value: str) -> Paise:
    value = value.strip()
    if not value:
        raise ValueError("is empty")
    if "." in value:
        raise ValueError("has a decimal point -- money is whole paise, not rupees")
    try:
        amount = int(value)
    except ValueError:
        raise ValueError(f"is not a whole number ({value!r})") from None
    if amount < 0:
        raise ValueError("is negative")
    return Paise(amount)


def signed_paise(value: str) -> Paise:
    """Adjustments and balances run both ways. Everything else must be positive."""
    value = value.strip()
    if value.startswith("-"):
        return Paise(-int(paise(value[1:])))
    return paise(value)


def one_of(*allowed: str):
    def check(value: str) -> str:
        value = value.strip()
        if value not in allowed:
            raise ValueError(f"is not one of {', '.join(allowed)}")
        return value
    return check


SCHEMAS: dict[str, dict] = {
    "orders.csv": {
        "order_id": ident, "created_at": day, "customer_ref": text,
        "customer_name": text, "pincode": text, "gross_amount_paise": paise,
        "status": text,
    },
    "payments.csv": {
        "payment_id": ident, "order_id": optional_ident, "captured_at": day,
        "amount_paise": paise, "method": one_of(*METHODS), "fee_paise": paise,
        "gst_paise": paise, "settlement_id": optional_ident, "status": text,
    },
    "refunds.csv": {
        "refund_id": ident, "payment_id": optional_ident, "created_at": day,
        "amount_paise": paise, "type": one_of(*REFUND_TYPES),
        "settlement_id": optional_ident, "status": text,
    },
    "settlements.csv": {
        "settlement_id": ident, "settled_at": day, "utr": text,
        "net_amount_paise": signed_paise, "fee_paise": paise, "gst_paise": paise,
        "refund_paise": paise, "adjustment_paise": signed_paise,
    },
    "bank_statement.csv": {
        "txn_date": day, "narration": text, "credit_paise": paise,
        "debit_paise": paise, "closing_balance_paise": signed_paise,
        "bank_ref": ident,
    },
}
KEYS = {
    "orders.csv": "order_id", "payments.csv": "payment_id", "refunds.csv": "refund_id",
    "settlements.csv": "settlement_id", "bank_statement.csv": "bank_ref",
}
ATTRS = {
    "orders.csv": "orders", "payments.csv": "payments", "refunds.csv": "refunds",
    "settlements.csv": "settlements", "bank_statement.csv": "bank",
}


# What identifies each file, for the "matched on" evidence the detection table prints.
# A required column that no other schema also requires is what actually discriminates;
# the shared ones (status, settlement_id) prove nothing on their own.
DISCRIMINATORS = {
    name: tuple(sorted(set(schema) - set().union(
        *(set(other) for other_name, other in SCHEMAS.items() if other_name != name))))
    for name, schema in SCHEMAS.items()
}


@dataclass(frozen=True)
class Detected:
    """One CSV, identified. `matched_on` is why -- the columns that named it."""
    path: Path
    schema: str
    matched_on: tuple[str, ...]
    rows: int


@dataclass
class Detection:
    mapping: dict[str, Path]
    found: list[Detected]
    skipped: list[Path]
    problems: list[str]
    choices: dict[str, list[Detected]]   # schema -> rival files, for the CLI to ask about


def _peek(path: Path) -> tuple[set[str], int]:
    """Header columns (stripped) and the number of data rows. Header only, then a count."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return set(), 0
        return {cell.strip() for cell in header}, sum(1 for _ in reader)


def detect(folder: Path) -> Detection:
    """Identify each CSV in `folder` by its header, not its name.

    A merchant's exports are named whatever their aggregator named them, so the filename
    carries no information the header does not. A file matches a schema when its columns
    are a *superset* of that schema's required ones -- real exports carry extra columns.

    Pure: it reads headers and counts rows, prints nothing and asks nothing. Everything
    interactive lives in the CLI, so the harness and the tests can never block on a person.
    """
    found: list[Detected] = []
    skipped: list[Path] = []
    problems: list[str] = []
    claims: dict[str, list[Detected]] = {}

    for path in sorted(folder.glob("*.csv")):
        header, rows = _peek(path)
        fits = [name for name, schema in SCHEMAS.items() if set(schema) <= header]
        if not fits:
            skipped.append(path)
            continue
        if len(fits) > 1:
            # One file satisfying two schemas is not a question a user can answer -- it
            # means the required-column sets are too weak to tell the files apart, and any
            # answer would be a guess at our schema definitions. Ours to fix, not theirs.
            problems.append(
                f"{path.name} satisfies {' and '.join(sorted(fits))}. Those signatures do "
                f"not discriminate; a required-column set needs tightening.")
            continue
        hit = Detected(path, fits[0], DISCRIMINATORS[fits[0]][:3], rows)
        found.append(hit)
        claims.setdefault(fits[0], []).append(hit)

    for name in SCHEMAS:
        if name not in claims:
            problems.append(
                f"No file has the {ATTRS[name]} columns. Expected a CSV containing "
                f"{', '.join(SCHEMAS[name])}.")

    choices = {name: hits for name, hits in claims.items() if len(hits) > 1}
    mapping = {name: hits[0].path for name, hits in claims.items() if len(hits) == 1}
    return Detection(mapping, found, skipped, problems, choices)


@dataclass
class Ledger:
    orders: list[dict]
    payments: list[dict]
    refunds: list[dict]
    settlements: list[dict]
    bank: list[dict]

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, attr)) for name, attr in ATTRS.items()}


def _problem(row_no: int, filename: str, column: str, reason: str) -> str:
    return (f"Row {row_no} in {filename}: {column} {reason}. "
            f"Fix the row or remove it, then run again.")


def _read(path: Path, schema: dict, key: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    seen: dict[str, int] = {}

    if not path.exists():
        return rows, [f"{path.name} is missing from {path.parent}. Add it, then run again."]

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        # Fieldnames are stripped, like every value is. Whitespace in a header is a
        # formatting artefact of whatever wrote the file -- an editor column-aligning the
        # columns, most likely -- and must never be the difference between a parsed row and
        # a rejected one. A column that is genuinely absent still fails loudly below.
        actual = {(name or "").strip(): name for name in (reader.fieldnames or [])}
        absent = [c for c in schema if c not in actual]
        if absent:
            return rows, [f"{path.name} has no {' or '.join(absent)} column. "
                          f"Add it, then run again."]

        for raw in reader:
            row_no, row, ok = reader.line_num, {}, True
            for column, parse in schema.items():
                try:
                    row[column] = parse(raw.get(actual[column]) or "")
                except ValueError as bad:
                    problems.append(_problem(row_no, path.name, column, str(bad)))
                    ok = False
            if not ok:
                continue
            if row[key] in seen:
                problems.append(_problem(row_no, path.name, key,
                                         f"repeats an id first used on row {seen[row[key]]}"))
                continue
            seen[row[key]] = row_no
            rows.append(row)
    return rows, problems


def load(folder: Path, mapping: dict[str, Path] | None = None) -> Ledger:
    """Load all five files, or raise with every problem found across all of them.

    `mapping` is what `detect` returned: schema name -> the file that carries it. Without
    it the filename convention is used, which is what detect finds anyway when the files
    happen to be named conventionally. Keeping that fallback is what lets every existing
    caller -- the harness, the match CLI, the tests -- go on passing a folder.
    """
    loaded, problems = {}, []
    for filename, schema in SCHEMAS.items():
        path = (mapping or {}).get(filename) or folder.joinpath(filename)
        rows, found = _read(path, schema, KEYS[filename])
        loaded[ATTRS[filename]] = rows
        problems.extend(found)
    if problems:
        raise IngestError(problems)
    return Ledger(**loaded)

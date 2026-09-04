"""    PYTHONPATH=src python -m ingest <folder> [--yes]

Detection is the default. Files are identified by what their headers contain, not by what
they are called, because a merchant's exports are named whatever their aggregator named
them. What it decided is printed before anything is read: the ladder refuses rather than
guesses, and this is that posture at the ingest boundary -- show the reading, then act.
"""

import sys
from pathlib import Path

from .load import IngestError, detect, load

CONVENTION = "or name them orders.csv, payments.csv, refunds.csv, settlements.csv, bank_statement.csv"


def _shown(folder: Path, path: Path) -> str:
    """folder/name, not the absolute path -- the table has to stay scannable."""
    return str(Path(folder.name).joinpath(path.name))


def _table(folder, found, skipped) -> None:
    names = [_shown(folder, h.path) for h in found] + [_shown(folder, p) for p in skipped]
    width = max((len(n) for n in names), default=0)
    for hit in sorted(found, key=lambda h: h.path.name):
        label = hit.schema.removesuffix(".csv").replace("_", " ")
        print(f"  {_shown(folder, hit.path):<{width}}  ->  {label:<16}{hit.rows:>7,} rows"
              f"   matched on {', '.join(hit.matched_on)}")
    for path in skipped:
        print(f"  {_shown(folder, path):<{width}}      skipped -- nothing it could be")


def _choose(schema: str, rivals: list) -> Path:
    """Two files carry one schema. A person knows which export they meant; we do not."""
    print(f"\n  {len(rivals)} files carry the {schema.removesuffix('.csv')} columns:")
    for n, hit in enumerate(rivals, 1):
        print(f"    [{n}] {hit.path}   {hit.rows:,} rows")
    while True:
        picked = input("  which one? ").strip()
        if picked.isdigit() and 1 <= int(picked) <= len(rivals):
            return rivals[int(picked) - 1].path
        print("  not one of those.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--yes"]
    assume_yes = "--yes" in sys.argv[1:]
    folder = Path(args[0] if args else "data/train")
    interactive = sys.stdin.isatty()

    found = detect(folder)
    print(f"\n  {folder}\n")
    _table(folder, found.found, found.skipped)

    # Ambiguity is never resolved by the absence of a human. With a person here we ask;
    # without one we stop. Neither path picks silently.
    if found.choices and not interactive:
        found.problems.extend(
            f"{len(hits)} files carry the {name.removesuffix('.csv')} columns "
            f"({', '.join(h.path.name for h in hits)}). Nothing here can choose between "
            f"them. Remove or rename one, or pass the folder to a run with a terminal."
            for name, hits in found.choices.items())

    if found.problems:
        print(f"\n  {len(found.problems)} problem(s). Nothing was loaded.\n")
        for problem in found.problems:
            print(f"  {problem}")
        print()
        sys.exit(1)

    for name, hits in found.choices.items():
        found.mapping[name] = _choose(name, hits)

    if interactive and not assume_yes:
        print("\n  looks right? [enter] to run  ·  [e] to correct")
        if input("  ").strip().lower() == "e":
            print(f"\n  Nothing was loaded. Rename the file you meant, {CONVENTION},\n"
                  f"  or point this at a folder holding only the five exports.\n")
            sys.exit(1)

    try:
        ledger = load(folder, found.mapping)
    except IngestError as bad:
        print(f"\n  {len(bad.problems)} rows could not be read. Nothing was loaded.\n")
        for problem in bad.problems:
            print(f"  {problem}")
        sys.exit(1)
    print("\n  " + "  ".join(f"{n} {f}" for f, n in ledger.counts().items()) + "\n")

"""    PYTHONPATH=src python -m match data/train

Rung counts only. Accuracy against the answer key is the eval harness, step 5.
"""

import sys
from pathlib import Path

from ingest.load import IngestError, load
from money import Paise, format_rupees

from .ladder import run

if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/train")
    try:
        ledger = load(folder)
    except IngestError as bad:
        print(f"{len(bad.problems)} rows could not be read. Nothing was loaded.\n")
        for problem in bad.problems:
            print(f"  {problem}")
        sys.exit(1)

    result = run(ledger)
    credits = len(ledger.bank)
    print(f"{folder}: {credits} bank credits, {len(ledger.settlements)} settlements\n")
    for rung, count in result.by_rung().items():
        share = count * 10000 // credits
        print(f"  {rung}  {count:5d} credits   {share // 100}.{share % 100:02d}%")
    print(f"\n  {len(result.unmatched_credits)} credits unmatched, "
          f"{len(result.unmatched_settlements)} settlements unmatched")
    print(f"  {len(result.flagged)} matches consumed tolerance, "
          f"drift absorbed {format_rupees(Paise(result.drift_paise))}")

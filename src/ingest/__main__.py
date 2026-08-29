"""    PYTHONPATH=src python -m ingest data/train"""

import sys
from pathlib import Path

from .load import IngestError, load

if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/train")
    try:
        ledger = load(folder)
    except IngestError as bad:
        print(f"{len(bad.problems)} rows could not be read. Nothing was loaded.\n")
        for problem in bad.problems:
            print(f"  {problem}")
        sys.exit(1)
    print(f"{folder}: " + "  ".join(f"{n} {f}" for f, n in ledger.counts().items()))

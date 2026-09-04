"""Build a dataset. CSVs go to data/<name>/, the answer key to eval/ground_truth/<name>.json.

The two live in different trees on purpose. The matching engine reads data/ and has no
reason to know eval/ exists -- PRD 8, asserted by a test.

    PYTHONPATH=src python -m generate train
    PYTHONPATH=src python -m generate heldout
"""

import json
import sys
from pathlib import Path
from random import Random

from . import breaks, world

SEEDS = {"train": 20260101, "heldout": 20260331}
ROOT = Path(__file__).resolve().parents[2]


def _assert_still_ambiguous(w: world.World) -> None:
    """Every subset an E14 names must still tie exactly to its credit after injection.

    Fails rather than drops. R2 spends no tolerance, so a decoy off by one paisa is not a
    weaker decoy, it is no decoy at all -- the solver would find one answer and match it,
    and the answer key would still be claiming ambiguity. With two or three E14s in a run,
    quietly discarding one is quietly discarding the population.
    """
    for a in w.ambiguous:
        target = w.credit(a["bank_ref"])["credit_paise"]
        for subset in [a["true_subset"], *a["decoy_subsets"]]:
            total = sum(w.settlement(sid)["net_amount_paise"] for sid in subset)
            assert total == target, (
                f"{a['bank_ref']}: subset {subset} is {total - target} paise off after "
                f"injection -- a break moved a record world._decoys had tied")


def build_dataset(name: str) -> tuple[world.World, list[dict], dict]:
    """Clean world, then damage, then both invariants. Returns world, breaks, answer key."""
    seed = SEEDS[name]
    w = world.build(seed)
    world.assert_identity(w)

    injected = breaks.injure(w, Random(seed + 1))
    world.recompute_in_transit(w)
    after = sum(row["credit_paise"] for row in w.bank)
    drift = w.credit_before_breaks + sum(b["delta_paise"] for b in injected) - after
    assert drift == 0, f"answer key disagrees with the CSVs by {drift} paise"
    _assert_still_ambiguous(w)

    key = {
        "seed": seed,
        "params": {
            "payments": world.N_PAYMENTS,
            "bundle_bps": world.BUNDLE_BPS,
            "bundle_size": [world.BUNDLE_MIN, world.BUNDLE_MAX],
            "utr_treatment_bps": world.UTR_TREATMENT_BPS,
            "decoy_window_days": world.DECOY_WINDOW_DAYS,
            "decoy_fill_max": world.DECOY_FILL_MAX,
            "decoy_size": [world.DECOY_MIN, world.DECOY_MAX],
            "decoys_attempted": w.decoys_attempted,
            "decoys_feasible": w.decoys_feasible,
            "tolerance_paise": breaks.TOLERANCE_PAISE,
        },
        "matches": w.matches,
        "ambiguous": w.ambiguous,
        "breaks": injected,
        "expected_fees": w.expected_fees,
        "totals": world.totals(w),
    }
    return w, injected, key


def main(name: str) -> None:
    w, injected, key = build_dataset(name)
    world.write(w, ROOT.joinpath("data", name))
    out = ROOT.joinpath("eval", "ground_truth")
    out.mkdir(parents=True, exist_ok=True)
    out.joinpath(f"{name}.json").write_text(json.dumps(key, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for b in injected:
        counts[b["code"]] = counts.get(b["code"], 0) + 1
    bundled = sum(1 for m in w.matches if len(m["settlement_ids"]) > 1)
    print(f"{name}: seed {key['seed']}")
    print(f"  {len(w.payments)} payments, {len(w.settlements)} settlements, "
          f"{len(w.bank)} bank rows, {bundled} bundled credits, "
          f"{len(w.ambiguous)} ambiguous (E14)")
    print(f"  {len(injected)} breaks: " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "train")

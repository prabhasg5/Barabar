"""R3: the LLM rung and its validator.

The safety rule this file guards is PRD 5's, verbatim: **the LLM proposes, deterministic code
disposes.** Every test here passes a hand-built proposal into `ladder.r3` rather than calling a
model -- the point is what the validator does with an arbitrary claim, and a real model is the
one thing that cannot be used to test that.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from ingest.load import load
from match.ladder import run
from propose.prompt import TAXONOMY, build, key_for

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeProposal:
    bank_ref: str = ""
    code: str = "MATCH"
    settlement_ids: tuple = ()
    confidence: int = 100
    explanation: str = "test"
    provider: str = "fake"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = True


@pytest.fixture(scope="module")
def train():
    return load(ROOT.joinpath("data", "train"))


def _run_with(ledger, make):
    """Run the ladder to R3 with a proposer built from the open candidates."""
    return run(ledger, through="R3",
               propose=lambda credit, candidates: make(credit, candidates))


def test_a_proposal_that_does_not_tie_is_rejected_at_any_confidence(train):
    """The whole safety rule in one assertion. A model claiming 100 confidence on settlements
    that do not sum to the credit gets nothing -- confidence is not evidence."""
    def greedy(credit, candidates):
        return FakeProposal(bank_ref=credit["bank_ref"], code="MATCH", confidence=100,
                            settlement_ids=tuple(s["settlement_id"] for s in candidates[:1]))
    result = _run_with(train, greedy)
    assert [m for m in result.matches if m.rung == "R3"] == [], \
        "a proposal was accepted without tying to the paisa"
    assert result.rejected, "the rejection was not recorded for the trail"


def test_a_proposal_that_ties_is_accepted_at_low_confidence():
    """The other direction, and the reason there is no threshold: a proposal that ties is
    correct at a stated confidence of 1.

    Built by hand rather than found in the data. Searching the dataset for a credit that
    happens to have an exactly-equal open settlement makes the test silently vacuous on any
    seed where none exists -- an empty assertion that reports green, which is the failure this
    project has now hit three times.
    """
    from match.ladder import Index, Result, r3

    credit = {"bank_ref": "HDFCTEST1", "credit_paise": 500_00,
              "txn_date": date(2026, 2, 10), "narration": "NEFT-RAZORPAY-X"}
    settlements = [
        {"settlement_id": "setl_a", "net_amount_paise": 300_00, "utr": "111",
         "settled_at": date(2026, 2, 9)},
        {"settlement_id": "setl_b", "net_amount_paise": 200_00, "utr": "222",
         "settled_at": date(2026, 2, 9)},
    ]
    idx = Index(settlements=settlements, by_utr={}, payments_of={})
    result = Result()
    result.trail["HDFCTEST1"] = []

    left = r3([credit], idx, result,
              lambda c, cands: FakeProposal(bank_ref=c["bank_ref"], code="MATCH",
                                            confidence=1,
                                            settlement_ids=("setl_a", "setl_b")))
    assert left == [], "a proposal that ties to the paisa was not accepted"
    assert [m.rung for m in result.matches] == ["R3"]
    assert result.matches[0].settlement_ids == ("setl_a", "setl_b")
    assert idx.claimed == {"setl_a", "setl_b"}, "accepted settlements were not claimed"


def test_the_same_proposal_one_paisa_out_is_refused_at_full_confidence():
    """One paisa is the whole difference. Guards against a tolerance creeping into R3: R0/R1
    spend 100 paise and R2 spends none, and R3 must never reach the looser figure."""
    from match.ladder import Index, Result, r3

    credit = {"bank_ref": "HDFCTEST2", "credit_paise": 500_01,
              "txn_date": date(2026, 2, 10), "narration": "NEFT-RAZORPAY-X"}
    settlements = [
        {"settlement_id": "setl_a", "net_amount_paise": 300_00, "utr": "111",
         "settled_at": date(2026, 2, 9)},
        {"settlement_id": "setl_b", "net_amount_paise": 200_00, "utr": "222",
         "settled_at": date(2026, 2, 9)},
    ]
    idx = Index(settlements=settlements, by_utr={}, payments_of={})
    result = Result()
    result.trail["HDFCTEST2"] = []

    left = r3([credit], idx, result,
              lambda c, cands: FakeProposal(bank_ref=c["bank_ref"], code="MATCH",
                                            confidence=100,
                                            settlement_ids=("setl_a", "setl_b")))
    assert left == [credit]
    assert result.matches == [] and len(result.rejected) == 1
    assert idx.claimed == set()


def test_a_credit_r2_refused_as_ambiguous_is_never_offered_to_the_model(train):
    """PRD 8 scores a claim on an ambiguous credit as FALSE even when it equals the true
    subset. On the first live run the model proposed one arm of a known E14 at confidence 100
    and an earlier validator accepted it -- correct, as it happens, and still a guess.

    Uniqueness cannot be re-checked at R3 time: by then R2 has claimed the rival subset's
    members against their own bundled credits, so only one subset is still open. Only R2's
    refusal carries the information, which is why this guard is a skip and not a re-check.
    """
    seen = []

    def spy(credit, candidates):
        seen.append(credit["bank_ref"])
        return FakeProposal(bank_ref=credit["bank_ref"], code="E01")

    result = _run_with(train, spy)
    base = run(train, through="R2")
    refused = {a.bank_ref for a in base.ambiguous}
    assert refused, "no E14 on train -- this test is asserting nothing"
    assert not (refused & set(seen)), f"an ambiguous credit was offered to the model: {refused & set(seen)}"
    assert not [m for m in result.matches if m.bank_ref in refused]


def test_the_prompt_is_built_from_the_taxonomy_not_from_a_dataset(train):
    """A prompt tuned until four particular rows read nicely is fitted to a sample of four --
    the same error as a threshold tuned on train. The prompt names every code and no row."""
    credit = train.bank[0]
    text = build(credit, train.settlements[:2])

    # Iterating TAXONOMY here would be a tautology: it is the dict that builds the text, so
    # `for code in TAXONOMY: assert code in text` cannot fail however the dict changes.
    # Renaming a key passed it. Bound to PRD 6's table instead, which is the taxonomy's owner
    # -- the same seam as the rate card and PRD 7.
    spec = ROOT.joinpath("PRD.md").read_text(encoding="utf-8")
    in_prd = set(re.findall(r"^\|\s*\**(E\d\d)\**\s*\|", spec, re.M))
    assert in_prd, "PRD 6's taxonomy table is no longer parseable"
    # Codes decided before R3 runs, or invisible to it, are deliberately not offered: the
    # model cannot usefully return a code the engine would only discard.
    not_offered = {"E03", "E05", "E06", "E07", "E08", "E09", "E10", "E11", "E12"}
    for code in sorted(in_prd - not_offered):
        assert code in TAXONOMY, f"{code} is in PRD 6 but not offered to the model"
        assert code in text, f"{code} is not described in the prompt"
    for code in sorted(TAXONOMY):
        assert code == "MATCH" or code in in_prd, f"{code} is offered but is not in PRD 6"
    for seed in ("train", "heldout", "SEED_TRAIN", "20260101", "20260331"):
        assert seed not in text, f"the prompt names a dataset: {seed}"


def test_the_cache_key_changes_with_the_model_but_not_with_run_order(train):
    """Two providers must not share an answer, or the two-provider comparison is circular.
    And the key must be stable across runs, or the cache misses every time."""
    credit = train.bank[0]
    a = build(credit, sorted(train.settlements[:3], key=lambda s: s["settlement_id"]))
    b = build(credit, sorted(train.settlements[:3], key=lambda s: s["settlement_id"]))
    assert key_for(a, "m1") == key_for(b, "m1")
    assert key_for(a, "m1") != key_for(a, "m2")


def test_r3_does_not_run_without_a_proposer(train):
    """The deterministic rungs must never depend on a model being reachable."""
    with pytest.raises(ValueError, match="R3 needs a proposer"):
        run(train, through="R3")


def test_the_cache_is_committed_and_replays_without_a_key(train, monkeypatch):
    """Criterion 4, and the thing that matters more than it: a stranger clones the repo and
    reproduces every number with no API key at all."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from functools import partial
    from propose import propose
    cache = ROOT.joinpath("llm_cache", "gemini.json")
    assert cache.exists(), "the response cache is not committed"
    assert json.loads(cache.read_text(encoding="utf-8")), "the cache is empty"
    first = run(train, through="R3",
                propose=partial(propose, provider="gemini", allow_api=False))
    second = run(train, through="R3",
                 propose=partial(propose, provider="gemini", allow_api=False))
    assert [(m.bank_ref, m.settlement_ids) for m in first.matches] == \
           [(m.bank_ref, m.settlement_ids) for m in second.matches]
    assert all(p.cached for p in first.proposals)

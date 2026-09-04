"""The response cache. This is a deliverable, not an optimisation.

Acceptance criterion 4 -- identical inputs produce identical output -- cannot hold for a model
call, and step 5 flagged that as unresolved. It is resolved here: the cache is keyed on a hash
of the exact prompt bytes plus the model id, committed to the repo, and read in preference to
the API on every run. So:

  * reruns are byte-identical, because after the first run nothing calls a model at all; and
  * **a stranger can clone the repo and reproduce every number with no API key**, which matters
    more than the determinism does.

The data is synthetic, so committing the responses leaks nothing.

A miss with no key raises rather than silently degrading. An R3 that quietly skips its rung
when a key is absent would report a coverage delta of zero that means "not run" while looking
exactly like a delta of zero that means "nothing left to find" -- and telling those two apart is
the entire finding of this step.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .prompt import build, key_for
from .providers import PROVIDERS, call

# Deliberately NOT under eval/. The ground-truth guard forbids anything in src/ from reading
# that tree, and it is right to: the cache is an *input* to the engine, and putting engine
# input beside the answer key is how the two start being confused for one another.
CACHE_DIR = Path(__file__).resolve().parents[2].joinpath("llm_cache")


@dataclass(frozen=True)
class Proposal:
    """What the model returned, before any validation. Not a match -- a candidate."""

    bank_ref: str
    code: str
    settlement_ids: tuple[str, ...]
    confidence: int              # 0-100, recorded only; see ARCHITECTURE.md
    explanation: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cached: bool


def _path(provider: str) -> Path:
    return CACHE_DIR.joinpath(f"{provider}.json")


def _load(provider: str) -> dict:
    path = _path(provider)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _store(provider: str, cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(provider).write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")


def _parse(raw: str) -> dict:
    """The model returns JSON. A model that returns something else gets one code, not a crash.

    Malformed output is a real operating condition, not an exceptional one, and PRD 4's
    no-silent-drops rule is about input rows rather than model replies -- but the reply still
    has to end somewhere legible.
    """
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {"code": "E13", "settlement_ids": [], "confidence": 0,
                "explanation": "The model did not return readable JSON for this row."}
    if not isinstance(out, dict):
        return {"code": "E13", "settlement_ids": [], "confidence": 0,
                "explanation": "The model returned JSON that was not an object."}
    return out


def propose(credit: dict, candidates: list[dict], provider: str,
            allow_api: bool = True) -> Proposal:
    """One credit, one provider. Cache first; the API only on a miss.

    `candidates` is sorted here rather than trusted from the caller, because the prompt bytes
    are the cache key and an unstable order would miss every time.
    """
    ordered = sorted(candidates, key=lambda s: s["settlement_id"])
    prompt = build(credit, ordered)
    key = key_for(prompt, PROVIDERS[provider])
    cache = _load(provider)

    if key in cache:
        hit = cache[key]
        return Proposal(credit["bank_ref"], hit["code"], tuple(hit["settlement_ids"]),
                        hit["confidence"], hit["explanation"], provider,
                        hit["prompt_tokens"], hit["completion_tokens"], cached=True)

    if not allow_api:
        raise KeyError(
            f"no cached response for {credit['bank_ref']} on {provider}, and the API is "
            f"disabled for this run. Regenerate the cache with allow_api=True.")

    raw, prompt_tokens, completion_tokens = call(prompt, provider)
    out = _parse(raw)
    cache[key] = {
        "bank_ref": credit["bank_ref"],
        "code": str(out.get("code", "E13")),
        "settlement_ids": [str(s) for s in out.get("settlement_ids", []) or []],
        "confidence": int(out.get("confidence", 0) or 0),
        "explanation": str(out.get("explanation", "")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    _store(provider, cache)
    hit = cache[key]
    return Proposal(credit["bank_ref"], hit["code"], tuple(hit["settlement_ids"]),
                    hit["confidence"], hit["explanation"], provider,
                    prompt_tokens, completion_tokens, cached=False)

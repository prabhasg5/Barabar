"""Two providers behind one function. The interface is deliberately thin.

`call(prompt, model) -> (text, prompt_tokens, completion_tokens)`. Nothing else crosses this
boundary: no SDK objects, no provider-shaped config, no streaming. Both providers are HTTP and
JSON, so `urllib` is enough and neither SDK is a dependency.

**Two providers on purpose.** If Gemini and Llama produce the same accepted-match count, the
validator is doing the work rather than the model -- which is the claim R3 exists to test. One
provider agreeing with itself proves nothing.

The key is read from the environment and never logged, never included in an error message, and
never written to the cache.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Resolved from Google AI Studio's live model list on 2026-09-01, not from memory. The newest
# stable Flash there is gemini-3.7-flash; it and gemini-flash-latest both returned HTTP 503
# ("high demand ... usually temporary") on every attempt that day, and gemini-2.5-flash is
# closed to new users. gemini-3.5-flash is the newest that actually served, so it is what the
# cache was built with. Pinned rather than chained to a fallback: a fallback would make the
# cache ambiguous about which model answered, and the two-provider comparison depends on
# knowing exactly that.
GEMINI_MODEL = "gemini-3.5-flash"
GROQ_MODEL = "llama-3.3-70b-versatile"
PROVIDERS = {"gemini": GEMINI_MODEL, "groq": GROQ_MODEL}


class NoKey(RuntimeError):
    """Raised when a run needs the API and the key is absent. Never carries the key."""


def _env(name: str) -> str:
    """Read from the process env, falling back to .env. Returns the value; never logs it."""
    if os.environ.get(name):
        return os.environ[name]
    dotenv = ROOT.joinpath(".env")
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip()
    raise NoKey(
        f"{name} is not set. R3 replays from the committed cache without it; a key is only "
        f"needed to regenerate the cache. Copy .env.example to .env to add one.")


def _post(url: str, payload: dict, headers: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as bad:
        # The body can echo the request. Take the status and nothing else.
        raise RuntimeError(f"provider returned HTTP {bad.code}") from None


def _post_with_retry(url: str, payload: dict, headers: dict, attempts: int = 3) -> dict:
    """Retry a transient 5xx. A hosted model returning 503 under load is an operating
    condition, not a bug, and a half-populated cache is worse than a slow run."""
    for attempt in range(attempts):
        try:
            return _post(url, payload, headers)
        except RuntimeError as bad:
            if attempt == attempts - 1 or " 5" not in str(bad):
                raise
    raise AssertionError("unreachable")


def _gemini(prompt: str, model: str) -> tuple[str, int, int]:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
           f"?key={_env('GEMINI_API_KEY')}")
    body = _post_with_retry(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }, {})
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    usage = body.get("usageMetadata", {})
    return text, usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)


def _groq(prompt: str, model: str) -> tuple[str, int, int]:
    body = _post_with_retry("https://api.groq.com/openai/v1/chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }, {"Authorization": f"Bearer {_env('GROQ_API_KEY')}"})
    usage = body.get("usage", {})
    return (body["choices"][0]["message"]["content"],
            usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


def call(prompt: str, provider: str) -> tuple[str, int, int]:
    """Ask one provider. Temperature 0 on both -- it does not make them deterministic, which
    is what the cache is for, but there is no reason to add variance on top."""
    if provider not in PROVIDERS:
        raise KeyError(f"unknown provider {provider!r}; have {', '.join(PROVIDERS)}")
    fn = _gemini if provider == "gemini" else _groq
    return fn(prompt, PROVIDERS[provider])

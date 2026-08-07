"""What a model *is*, as opposed to whether it answers.

`preflight` measures behaviour: does it reply, how fast, can it produce JSON,
how often does it fail. That is the strongest evidence there is, and it says
nothing about whether a model is any good at strategy — which is exactly what
the hard tier needs to know.

Three sources, and the repo's rule that every number is labelled applies:

- **Measured** (`preflight`) — what it actually did here. Always outranks the
  rest. `cerebras:gpt-oss-120b` *declares* structured-output support and was
  measured unable to return a JSON object; the measurement wins.
- **Given** — the provider's own catalogue. OpenRouter publishes, for 365
  models, the context window, the creation date (which is what "generation"
  means in practice), whether the model takes a `reasoning` parameter, and
  whether it claims structured outputs. It is a provider already in the
  registry, it needs no key, and it is maintained by someone whose business
  depends on it being right.
- **Estimated** — parameter count read out of the model's own name (`70b`,
  `gpt-oss-120b`, `nemotron-nano-9b`). A guess, labelled as one, and the only
  signal available for a model no catalogue describes.

**Why not a benchmark leaderboard.** They exist — llm-stats, Vellum, BenchLM,
iternal — and they are web products, not stable versioned APIs. Scraping one
would add an external dependency that rots silently, which is the precise
failure this project keeps paying for: openrouter's pinned `default_model`
stopped existing while nothing noticed. An operator who has a table they trust
can point `CORP_MODEL_SCORES` at it and it is merged as Given data, dated and
attributed, without the repo pretending to maintain one.

Nothing here runs on its own. The catalogue is fetched on demand and cached in
the store, like the hardware bench and the preflight.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from ..config import cfg

log = logging.getLogger("corparius.modelinfo")

CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
CACHE_KEY = "CORP_MODEL_CATALOGUE"
# The catalogue is a description of the world, not a measurement of this
# machine, so it may be a month stale without misleading anyone.
FRESH_DAYS = 30

MEASURED, GIVEN, ESTIMATED, UNKNOWN = "measured", "given", "estimated", "unknown"

# `llama-3.3-70b-versatile` -> 70. Also catches `120b`, `8x7b` (takes 7, the
# expert size, which is what matters for capability) and `nano-9b`.
_SIZE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b\b", re.I)


def size_b(model: str) -> float:
    """Parameter count in billions, read from the name. Estimated, and a guess.

    Deliberately crude. It exists because a model no catalogue lists still has
    to be placed somewhere, and `nemotron-nano-9b` next to `nemotron-super-120b`
    is real information sitting in plain sight.
    """
    found = _SIZE.findall(str(model or "").lower())
    if not found:
        return 0.0
    # The largest number in the name: `llama-3.1-8b` gives 8, and
    # `qwen2.5-coder-14b` gives 14 rather than the 2.5 of the version.
    return max(float(x) for x in found)


def _normalise(model: str) -> str:
    """A key that survives the same model being renamed by each provider.

    `groq:llama-3.3-70b-versatile`, `openrouter:meta-llama/llama-3.3-70b-instruct`
    and `nvidia:meta/llama-3.3-70b-instruct` are one model wearing three names.
    """
    name = str(model or "").lower().strip()
    # A leading `provider:` first. Stripping "everything after the first colon"
    # turned `groq:llama-3.3-70b-versatile` into `groq`, which matched nothing —
    # and silently, so routing simply stopped seeing any capability data.
    if ":" in name and "/" not in name.split(":", 1)[0]:
        name = name.split(":", 1)[1]
    name = name.split("/")[-1]
    name = re.sub(r"[:@].*$", "", name)  # openrouter's trailing `:free`
    name = re.sub(r"-(instruct|it|chat|versatile|latest|preview|free|hf|turbo)\b", "", name)
    return re.sub(r"[^a-z0-9.]+", "", name)


def fetch(timeout: int = 20) -> dict[str, dict]:
    """The provider catalogue, normalised name -> metadata. {} on any failure.

    No key: this endpoint is public, which is why it is the one used. A
    catalogue that cannot be reached is not an error — it means the Given layer
    is empty and routing falls back to Measured and Estimated alone.
    """
    try:
        response = requests.get(CATALOGUE_URL, timeout=timeout)
        response.raise_for_status()
        rows = response.json().get("data") or []
    except (requests.RequestException, ValueError, AttributeError) as exc:
        log.info("model catalogue unavailable: %s", exc)
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        ident = str(row.get("id") or "")
        if not ident:
            continue
        params = row.get("supported_parameters") or []
        # What a model takes in, which the response has always carried and this
        # function used to drop on the floor. The product told operators an image
        # was "offered to the models that accept images" while holding nothing
        # that could tell one from the other — measured on the live catalogue:
        # 180 of 337 entries declare image input, and only 5 of those are free.
        # Given, not Measured: a catalogue says what a model claims. What it can
        # actually do is preflight's business.
        modalities = (row.get("architecture") or {}).get("input_modalities") or []
        entry = {
            "id": ident,
            "context": int(row.get("context_length") or 0),
            "created": float(row.get("created") or 0),
            "reasoning": "reasoning" in params,
            "structured": "structured_outputs" in params or "response_format" in params,
            "tools": "tools" in params,
            "vision": "image" in modalities,
            "params_b": size_b(ident),
        }
        # First wins: the catalogue lists variants of the same model and the
        # canonical id comes before the dated snapshots.
        out.setdefault(_normalise(ident), entry)
    return out


def cached(store) -> dict[str, dict]:
    """Whatever catalogue is already on disk. **Never fetches.**

    Routing calls this, and a routing decision must not depend on the network
    being up — nor spend a request every time somebody presses "use recommended
    routing". The first version fetched here and it showed immediately: a unit
    test of the CLI made a live call to openrouter, and the 400 KB result landed
    in the settings table where the operator would see it as a setting.

    `refresh()` is the one that goes out, and it is called from the preflight,
    which is already the place that costs money on purpose.
    """
    if store is None:
        return {}
    try:
        return store.model_catalogue()
    except Exception:  # noqa: BLE001 - a missing cache must never break routing
        return {}


def refresh(store, timeout: int = 20) -> dict[str, dict]:
    """Fetch the catalogue and remember it. Returns what is now known.

    Keeps the previous copy when the fetch fails: one bad afternoon should not
    cost the routing layer everything it knew.
    """
    models = fetch(timeout)
    if not models:
        return cached(store)
    if store is not None:
        store.save_model_catalogue(models)
    return models


def age_days(store) -> float:
    """How old the cached catalogue is, or -1 when there is none."""
    if store is None:
        return -1.0
    ts = store.model_catalogue_ts()
    return -1.0 if not ts else (time.time() - ts) / 86400


def operator_scores() -> dict[str, float]:
    """A score table the operator maintains, keyed by normalised model name.

    `CORP_MODEL_SCORES=/path/to/scores.json`, holding `{"model": 0-100}`. This
    is how somebody who trusts a particular leaderboard uses it without this
    repo shipping a frozen copy of one — a table baked in here would rot exactly
    as the pinned `default_model` did, and nobody would notice.
    """
    path = cfg.get("CORP_MODEL_SCORES", "").strip()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("CORP_MODEL_SCORES at %s could not be read: %s", path, exc)
        return {}
    out = {}
    for name, value in (raw or {}).items():
        try:
            out[_normalise(str(name))] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def describe(
    model: str, catalogue: dict[str, dict], scores: dict[str, float] | None = None
) -> dict:
    """Everything known about one model, each field carrying where it came from."""
    key = _normalise(model)
    given = catalogue.get(key) or {}
    estimated = size_b(model)
    score = (scores or {}).get(key)
    return {
        "matched": bool(given),
        "source": GIVEN if given else (ESTIMATED if estimated else UNKNOWN),
        "context": given.get("context", 0),
        "created": given.get("created", 0.0),
        "reasoning": bool(given.get("reasoning")),
        "structured_declared": bool(given.get("structured")),
        # `_declared` for the same reason as structured: this is the claim, and
        # the claim and the measurement disagree often enough that the two must
        # never share a name. A model absent from the catalogue reads False, which
        # is "nothing says it can" and not "it cannot".
        "vision_declared": bool(given.get("vision")),
        "tools": bool(given.get("tools")),
        # The catalogue's own parsed size where it matched, otherwise the name.
        "params_b": given.get("params_b") or estimated,
        "score": score,
    }

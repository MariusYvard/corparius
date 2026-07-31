"""Which models this account can actually call, proved by calling them.

A provider's catalogue is a list of models that *exist*, not a list of models
*you* may use. `/models` happily returns names that answer 404 for your key:
a paid tier you are not on, a preview you were never granted, a region your
account is not in. corparius routed tiers off that list and could therefore
configure a model that fails on the first real turn — which is the worst place
to find out, mid-run, with a company depending on it.

So this asks the only question that matters: send eight tokens and see.

**What a failure means is the whole design.** The free tiers this project is
built around go cold, rate-limit, and return 503 while a model loads. Treating
any error as "unusable" would reject models that work perfectly a minute later,
which is worse than the catalogue it replaces. So:

- **200** — usable. Proved, not assumed.
- **404**, or a 400 naming the model — blocking. This account cannot call it.
- **401 / 403** — blocking, but the key is the problem, not the model.
- **429 / 500 / 502 / 503 / 504 / timeout / connection reset** — *momentary
  capacity*. Not a verdict. A cold free tier looks exactly like this.

Nothing here runs on its own. A probe costs a real generation on a real
account, and the doctor is run on every launcher start and served over HTTP —
probing there would be the polled-endpoint mistake with somebody's money
attached. `corparius preflight` runs it; the doctor reads the cached result and
never measures, exactly as it does for the hardware bench.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import requests

from . import cfg
from .llm import OPENAI_COMPAT_PROVIDERS, _split

log = logging.getLogger("corparius.preflight")

# Eight tokens out, a handful in. Small enough that probing every tier of every
# configured provider costs less than one ordinary agent turn.
MAX_TOKENS = 8
PROMPT = "Reply with the single word: ok"
TIMEOUT = 25

USABLE = "usable"
BLOCKED = "blocked"
CAPACITY = "capacity"
UNKNOWN = "unknown"

# Transient by nature. 500 is in here on purpose: several free gateways return a
# bare 500 while a model cold-starts, and a model that answers a minute later is
# not a model to remove from someone's configuration.
_TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class Probe:
    """One (provider, model) tried for real."""

    provider: str
    model: str
    tier: str = ""
    state: str = UNKNOWN
    detail: str = ""
    status: int = 0
    ms: int = 0
    reply: str = ""

    @property
    def ok(self) -> bool:
        """Usable *or* momentarily unavailable. `ok` qualifies the request, not
        the verdict: a 429 is not evidence against the model."""
        return self.state in (USABLE, CAPACITY)

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "tier": self.tier,
            "state": self.state,
            "detail": self.detail,
            "status": self.status,
            "ms": self.ms,
        }


def _classify(status: int, body: str, model: str) -> tuple[str, str]:
    """(state, detail) for an HTTP answer that was not a success."""
    text = (body or "").strip()
    short = " ".join(text.split())[:180]
    if status in _TRANSIENT:
        return CAPACITY, f"HTTP {status} — momentary capacity, not a verdict. {short}".strip()
    if status in (401, 403):
        return BLOCKED, f"HTTP {status} — the key is refused, so no model can be proved. {short}"
    if status == 404:
        return BLOCKED, f"HTTP 404 — this account cannot call {model}. {short}"
    if status == 400 and (model.lower() in text.lower() or "model" in text.lower()):
        # Several OpenAI-compatible gateways answer 400 rather than 404 for a
        # model you may not use. The message names it; a generic 400 does not.
        return BLOCKED, f"HTTP 400 naming the model — not callable with this key. {short}"
    return UNKNOWN, f"HTTP {status}. {short}".strip()


def probe(provider: str, model: str, tier: str = "", timeout: int = TIMEOUT) -> Probe:
    """One real eight-token generation. Never raises."""
    result = Probe(provider=provider, model=model, tier=tier)
    spec = OPENAI_COMPAT_PROVIDERS.get(provider)
    if spec is None:
        result.state, result.detail = UNKNOWN, f"{provider} is not a registered provider"
        return result
    base = (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base", "")).rstrip("/")
    if not base:
        result.state, result.detail = UNKNOWN, "no endpoint configured"
        return result
    key = cfg.get(spec["key_env"], "").strip()
    if not key and not spec.get("key_optional"):
        result.state, result.detail = UNKNOWN, "no key set, so nothing can be proved"
        return result

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }
    started = time.monotonic()
    try:
        response = requests.post(
            f"{base}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
    except requests.Timeout:
        result.ms = int((time.monotonic() - started) * 1000)
        result.state = CAPACITY
        result.detail = f"no answer in {timeout}s — momentary capacity, not a verdict"
        return result
    except requests.RequestException as exc:
        result.ms = int((time.monotonic() - started) * 1000)
        result.state = CAPACITY
        result.detail = f"{type(exc).__name__} — the provider could not be reached right now"
        return result

    result.ms = int((time.monotonic() - started) * 1000)
    result.status = response.status_code
    if response.status_code >= 400:
        result.state, result.detail = _classify(response.status_code, response.text[:400], model)
        return result
    try:
        data = response.json()
        choices = data.get("choices") or []
        # `or ""` because a provider may answer 200 with `content: null`
        # (openrouter's free tier does). `str(None)` would put the word "None"
        # in the report as if the model had said it.
        result.reply = str((choices[0].get("message") or {}).get("content") or "")[:120]
    except (ValueError, AttributeError, IndexError, KeyError):
        # 200 with a shape nobody expected. It answered, which is what was being
        # asked, but an empty body is not proof it can do useful work.
        result.state = UNKNOWN
        result.detail = "answered 200 with a body this build could not read"
        return result
    result.state = USABLE
    result.detail = f"answered in {result.ms} ms"
    return result


@dataclass
class Report:
    probes: list[Probe] = field(default_factory=list)
    ts: float = 0.0

    @property
    def blocking(self) -> list[Probe]:
        return [p for p in self.probes if p.state == BLOCKED]

    @property
    def transient(self) -> list[Probe]:
        return [p for p in self.probes if p.state == CAPACITY]

    def as_dict(self) -> dict:
        return {"ts": self.ts, "probes": [p.as_dict() for p in self.probes]}


def skipped(settings) -> list[tuple[str, str]]:
    """(tier, model) this cannot prove, and why it is not a defect.

    `claudecode:` runs through the local Claude CLI and `local:` through Ollama;
    neither speaks the OpenAI chat API this probes. Reported rather than dropped,
    because a preflight that silently covers three of six tiers and says
    "everything checks out" is worse than one that admits its reach.
    """
    out = []
    tiers = [
        ("trivial", settings.trivial_model),
        ("normal", settings.normal_model),
        ("hard", settings.hard_model),
    ]
    fallback = getattr(settings, "llm_fallback", "") or []
    steps = fallback if isinstance(fallback, (list, tuple)) else str(fallback).split(",")
    tiers += [("fallback", str(s).strip()) for s in steps if str(s).strip()]
    for tier, model in tiers:
        provider, name = _split(str(model or ""))
        if model and (provider not in OPENAI_COMPAT_PROVIDERS or not name):
            out.append((tier, str(model)))
    return out


def targets(settings) -> list[tuple[str, str, str]]:
    """(tier, provider, model) for every role the operator has configured.

    Role by role rather than provider by provider: what matters is whether *the
    model this tier will actually call* answers, and two tiers may sit on the
    same provider with different models — one fine, one not.
    """
    out = []
    for tier, model in (
        ("trivial", settings.trivial_model),
        ("normal", settings.normal_model),
        ("hard", settings.hard_model),
    ):
        provider, name = _split(str(model or ""))
        if provider in OPENAI_COMPAT_PROVIDERS and name:
            out.append((tier, provider, name))
    # `llm_fallback` is already a list on Settings; it is a comma string only in
    # the environment. Treating it as a string gave `["['cerebras:gpt-oss-120b'",
    # " 'mistral:...'"]` and silently probed none of the fallbacks — found by
    # running this against a real configuration, not by reading it.
    fallback = getattr(settings, "llm_fallback", "") or []
    steps = fallback if isinstance(fallback, (list, tuple)) else str(fallback).split(",")
    for step in steps:
        provider, name = _split(str(step).strip())
        if provider in OPENAI_COMPAT_PROVIDERS and name:
            out.append(("fallback", provider, name))
    # Same model twice is one probe: the answer cannot differ, and each probe is
    # a real call on the operator's account.
    seen, unique = set(), []
    for tier, provider, name in out:
        if (provider, name) in seen:
            continue
        seen.add((provider, name))
        unique.append((tier, provider, name))
    return unique


def run(settings, timeout: int = TIMEOUT) -> Report:
    """Probe every configured tier for real. Costs one small generation each."""
    report = Report(ts=time.time())
    if getattr(settings, "llm_mock", False):
        log.info("preflight: mock mode, nothing to prove")
        return report
    for tier, provider, model in targets(settings):
        result = probe(provider, model, tier, timeout=timeout)
        log.info("preflight %s %s:%s -> %s (%s)", tier, provider, model, result.state, result.ms)
        report.probes.append(result)
    return report


def probe_catalogue(provider: str, limit: int = 0, timeout: int = TIMEOUT) -> list[Probe]:
    """Call every model the provider advertises, and see which ones answer.

    This is where the gap between a catalogue and an account is widest.
    Measured on NVIDIA with the owner's own key: **8 of 14 sampled entries
    answered 404** out of a catalogue of 102. Picking a tier off that list is
    close to a coin flip.

    `limit` caps the number of calls, because a full sweep of a large catalogue
    is a hundred real generations. Zero means all of them, which is a deliberate
    thing to ask for.
    """
    from .llm import list_models

    try:
        models = list_models(provider, timeout=timeout)
    except (requests.RequestException, ValueError) as exc:
        log.warning("preflight: %s did not answer with a catalogue: %s", provider, exc)
        return []
    if limit > 0:
        # Spread across the catalogue rather than the first N: providers list
        # alphabetically, and the first twenty of "01-ai…" through "ai21labs…"
        # are not a sample of anything.
        step = max(1, len(models) // limit)
        models = models[::step][:limit]
    return [probe(provider, model, "catalogue", timeout=timeout) for model in models]


def remember(store, probes: list[Probe]) -> None:
    """Write each verdict into the per-provider memory.

    Separate from `save`: that keeps the last *run* for the doctor to summarise,
    this accumulates what is known about each model across every run. The first
    version had only the former, so the same 404s were rediscovered every time.
    """
    if store is None:
        return
    for p in probes:
        if p.state == UNKNOWN and not p.status:
            continue  # nothing was called; there is nothing to remember
        store.record_probe(p.provider, p.model, p.state, p.detail, p.status, p.ms)


def known(store, provider: str = "") -> dict[str, list[str]]:
    """{provider: [models proved usable]}, from everything ever probed."""
    if store is None:
        return {}
    out: dict[str, list[str]] = {}
    for row in store.known_probes(provider):
        if row["state"] == USABLE:
            out.setdefault(row["provider"], []).append(row["model"])
    return out


def save(store, report: Report) -> None:
    """Remember it, so the doctor can report without ever probing."""
    if store is None:
        return
    store.set_setting("CORP_PREFLIGHT", json.dumps(report.as_dict()))
    remember(store, report.probes)


def load(store) -> Report:
    """The last run, or an empty report. Never probes."""
    if store is None:
        return Report()
    raw = store.get_setting("CORP_PREFLIGHT") or ""
    if not raw:
        return Report()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Report()
    probes = [
        Probe(
            provider=str(p.get("provider", "")),
            model=str(p.get("model", "")),
            tier=str(p.get("tier", "")),
            state=str(p.get("state", UNKNOWN)),
            detail=str(p.get("detail", "")),
            status=int(p.get("status", 0) or 0),
            ms=int(p.get("ms", 0) or 0),
        )
        for p in data.get("probes", [])
    ]
    return Report(probes=probes, ts=float(data.get("ts", 0) or 0))

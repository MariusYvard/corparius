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

import base64
import json
import logging
import statistics
import time
from dataclasses import dataclass, field

import requests

from .config import cfg
from .config.provider_table import OPENAI_COMPAT_PROVIDERS, split_target
from .llm import list_models
from .routing import BLOCKED, CAPACITY, UNKNOWN, USABLE

log = logging.getLogger("corparius.preflight")

# Eight tokens out, a handful in. Small enough that probing every tier of every
# configured provider costs less than one ordinary agent turn.
MAX_TOKENS = 8
PROMPT = "Reply with the single word: ok"
TIMEOUT = 25


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


# A richer measurement than "did it answer", for the handful of models a tier
# might actually be routed to. Deliberately not run across a 365-model
# catalogue: availability is cheap to ask, performance is not.
MEASURE_TOKENS = 48
MEASURE_SAMPLES = 3
# The one capability the whole runtime depends on. Every agent tool with a
# schema goes through corparius/structured.py, so a model that cannot return
# parseable JSON is useless for most of the roster however fast it is — and
# that is invisible to an availability probe, which only asks for one word.
JSON_PROMPT = 'Answer with only this JSON object and nothing else: {"ok": true, "n": 7}'

# The same argument, for images. A catalogue entry that lists `image` among its
# input modalities is a claim, and this project already knows what a capability
# claim is worth: one model in a real fallback chain announces structured output
# and cannot produce an object. So the claim gets tested by sending a picture.
#
# Two colours in a known order, not one. "What colour is this square" is a
# question a model that sees nothing can answer correctly by guessing, and a probe
# a blind model passes measures nothing.
VISION_PROMPT = (
    "The image is a square split into two halves. Reply with exactly two words, "
    "lowercase, no punctuation: the colour of the top half, then the colour of "
    "the bottom half."
)
VISION_TOP, VISION_BOTTOM = "blue", "yellow"


def _solid_png(rows: list[tuple[int, int, int]], side: int = 8) -> bytes:
    """A tiny truecolour PNG, built here rather than shipped as a binary fixture.

    Stdlib only (`zlib`, `struct`), like every other format this project reads and
    writes. One row of `rows` per band, top to bottom.
    """
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    height = side * len(rows)
    scanlines = b"".join(b"\x00" + bytes(colour) * side for colour in rows for _ in range(side))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", side, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def vision_png() -> bytes:
    """The probe image: blue over yellow."""
    return _solid_png([(0, 0, 255), (255, 255, 0)])


def vision_probe(provider: str, model: str, timeout: int = TIMEOUT) -> bool | None:
    """Send a picture and see whether the model can read it.

    True, False, or None when the call never got far enough to tell — a transport
    failure is not a verdict, and storing it as one would mark a model blind
    because a laptop was on a train.

    One call, not a sample of several: this answers a yes/no, and the image makes
    it the most expensive request in this module.
    """
    spec = OPENAI_COMPAT_PROVIDERS.get(provider)
    if spec is None:
        return None
    base = (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base", "")).rstrip("/")
    key = cfg.get(spec["key_env"], "").strip()
    if not base or (not key and not spec.get("key_optional")):
        return None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data_uri = "data:image/png;base64," + base64.b64encode(vision_png()).decode()
    try:
        response = requests.post(
            f"{base}/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
                "max_tokens": MEASURE_TOKENS,
                "temperature": 0,
            },
            headers=headers,
            timeout=timeout,
        )
    except (requests.RequestException, ValueError):
        return None
    if response.status_code >= 400:
        # A refusal is an answer: most gateways reject an image for a text-only
        # model with a 400, and that is exactly the thing being measured.
        return False
    try:
        text = str((response.json()["choices"][0].get("message") or {}).get("content") or "")
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    said = text.lower()
    top, bottom = said.find(VISION_TOP), said.find(VISION_BOTTOM)
    # Both colours, in the right order. Naming them the other way round is the
    # answer of something that read the prompt and not the picture.
    return top >= 0 and bottom > top


@dataclass
class Measurement:
    """What a model does under a slightly realistic ask, sampled more than once.

    Measured before this existed: four identical 8-token calls to the same model
    spanned 465–774 ms. A single sample is not a measurement, and routing on one
    would be routing on noise.
    """

    provider: str
    model: str
    samples: int = 0
    failures: int = 0
    ms: int = 0  # median wall clock
    tok_s: float = 0.0  # median, from the provider's own timing where given
    json_ok: bool = False
    # None means nobody asked, which is not the same answer as "cannot see".
    vision_ok: bool | None = None

    @property
    def reliability(self) -> float:
        return 0.0 if not self.samples else 1.0 - (self.failures / self.samples)


def measure(
    provider: str,
    model: str,
    samples: int = MEASURE_SAMPLES,
    timeout: int = TIMEOUT,
    vision: bool = False,
) -> Measurement:
    """Sample a model several times and report speed, throughput and whether it
    can produce JSON at all.

    `vision` adds one more call, with a picture in it. Off by default and asked
    for by the caller, because the image makes it the most expensive request here
    and it is only worth spending on a model that claims to accept one.

    Throughput comes from the provider's own `usage.completion_time` when it
    sends one (groq, cerebras and most OpenAI-compatible gateways do), because
    wall clock over a WAN measures the network as much as the model. It falls
    back to wall clock when the provider says nothing.
    """
    out = Measurement(provider=provider, model=model)
    lat: list[int] = []
    rates: list[float] = []
    json_seen = 0
    for _ in range(max(1, samples)):
        one = _one_measure(provider, model, timeout)
        out.samples += 1
        if one is None:
            out.failures += 1
            continue
        ms, tok_s, ok_json = one
        lat.append(ms)
        if tok_s:
            rates.append(tok_s)
        json_seen += int(ok_json)
    if lat:
        out.ms = int(statistics.median(lat))
    if rates:
        out.tok_s = round(statistics.median(rates), 1)
    # Every successful sample, not just one: a model that produces JSON two
    # times in three is a model that breaks a tool one turn in three.
    out.json_ok = bool(lat) and json_seen == len(lat)
    # Only if something answered at all: sending a picture to a model that just
    # failed three plain calls buys a fourth failure and a bigger bill.
    if vision and lat:
        out.vision_ok = vision_probe(provider, model, timeout)
    return out


def _one_measure(provider: str, model: str, timeout: int):
    """(ms, tokens_per_second, json_parsed) or None if the sample failed."""
    spec = OPENAI_COMPAT_PROVIDERS.get(provider)
    if spec is None:
        return None
    base = (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base", "")).rstrip("/")
    key = cfg.get(spec["key_env"], "").strip()
    if not base or (not key and not spec.get("key_optional")):
        return None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    started = time.monotonic()
    try:
        response = requests.post(
            f"{base}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": JSON_PROMPT}],
                "max_tokens": MEASURE_TOKENS,
                "temperature": 0,
            },
            headers=headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            return None
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    ms = int((time.monotonic() - started) * 1000)
    text = ""
    try:
        text = str((data["choices"][0].get("message") or {}).get("content") or "")
    except (KeyError, IndexError, TypeError):
        return None

    usage = data.get("usage") or {}
    completion = float(usage.get("completion_tokens") or 0)
    elapsed = float(usage.get("completion_time") or 0)
    tok_s = completion / elapsed if completion and elapsed > 0 else 0.0
    if not tok_s and completion and ms:
        tok_s = completion / (ms / 1000)

    json_ok = False
    snippet = text.strip().strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(snippet[snippet.find("{") : snippet.rfind("}") + 1] or snippet)
        json_ok = isinstance(parsed, dict) and "ok" in parsed
    except (json.JSONDecodeError, ValueError):
        json_ok = False
    return ms, tok_s, json_ok


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
        provider, name = split_target(str(model or ""))
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
        provider, name = split_target(str(model or ""))
        if provider in OPENAI_COMPAT_PROVIDERS and name:
            out.append((tier, provider, name))
    # `llm_fallback` is already a list on Settings; it is a comma string only in
    # the environment. Treating it as a string gave `["['cerebras:gpt-oss-120b'",
    # " 'mistral:...'"]` and silently probed none of the fallbacks — found by
    # running this against a real configuration, not by reading it.
    fallback = getattr(settings, "llm_fallback", "") or []
    steps = fallback if isinstance(fallback, (list, tuple)) else str(fallback).split(",")
    for step in steps:
        provider, name = split_target(str(step).strip())
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


def configured_providers() -> list[str]:
    """Providers this machine has a key for, so a sweep does not spend a minute
    proving that fourteen unconfigured endpoints are unconfigured."""
    out = []
    for name, spec in OPENAI_COMPAT_PROVIDERS.items():
        if cfg.get(spec["key_env"], "").strip() or spec.get("key_optional"):
            if cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base"):
                out.append(name)
    return sorted(out)


def estimate(timeout: int = 8) -> dict:
    """How many real calls a full sweep would be, before anyone commits to it.

    Reading a catalogue is cheap; calling every entry in it is not. NVIDIA alone
    advertises 102 models. An operator pressing "check everything" deserves the
    number first — this is their money and their rate limits.
    """
    per: dict[str, int] = {}
    for name in configured_providers():
        try:
            per[name] = len(list_models(name, timeout=timeout))
        except (requests.RequestException, ValueError):
            per[name] = 0
    return {"providers": per, "total": sum(per.values())}


def sweep(
    store,
    limit: int = 0,
    timeout: int = TIMEOUT,
    on_progress=None,
    should_stop=None,
) -> dict:
    """Call every model of every configured provider, remembering as it goes.

    Written to be interrupted and resumed: each verdict is stored the moment it
    arrives, so a sweep stopped halfway has still taught the machine everything
    it proved up to that point. Losing an hour of real calls because the last
    provider timed out would be its own kind of waste.

    Providers run one after another rather than in parallel on purpose. These
    are rate-limited free tiers; hammering four at once is how a sweep turns
    every answer into a 429 and proves nothing.
    """
    counts = {"usable": 0, "blocked": 0, "capacity": 0, "unknown": 0}
    done = 0
    # Anything provisional or old goes first, so a sweep that is stopped early
    # has spent its calls on the questions actually worth asking again rather
    # than on re-confirming what was proved this morning.
    priority = {(p, m) for p, m, _ in stale(store)}
    for name in configured_providers():
        if should_stop and should_stop():
            break
        try:
            models = list_models(name, timeout=timeout)
        except (requests.RequestException, ValueError) as exc:
            log.warning("sweep: %s has no reachable catalogue: %s", name, exc)
            continue
        if limit > 0 and len(models) > limit:
            step = max(1, len(models) // limit)
            models = models[::step][:limit]
        models.sort(key=lambda m: (name, m) not in priority)
        for model in models:
            if should_stop and should_stop():
                break
            result = probe(name, model, "catalogue", timeout=timeout)
            remember(store, [result])
            counts[result.state] = counts.get(result.state, 0) + 1
            done += 1
            if on_progress:
                on_progress(name, model, result, done)
    return {"counts": counts, "probed": done}


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


def save_measurement(store, m: Measurement) -> None:
    if store is None or not m.samples:
        return
    store.record_measurement(
        m.provider, m.model, m.tok_s, m.json_ok, m.samples, m.failures, m.vision_ok
    )


def proven_map(store, provider: str = "") -> dict[str, dict[str, dict]]:
    """{provider: {model: {state, ms, ts, age_days}}} — everything measured.

    Richer than `known` because a routing decision needs the blocked ones too:
    the point is not only "what works" but "never pick the pinned default that
    is known to 404".
    """
    if store is None:
        return {}
    now = time.time()
    out: dict[str, dict[str, dict]] = {}
    for row in store.known_probes(provider):
        samples = int(row["samples"] or 0) if "samples" in row.keys() else 0
        failures = int(row["failures"] or 0) if "failures" in row.keys() else 0
        out.setdefault(row["provider"], {})[row["model"]] = {
            "state": row["state"],
            "ms": int(row["ms"] or 0),
            "ts": float(row["ts"] or 0),
            "age_days": int(max(0.0, now - float(row["ts"] or now)) / 86400),
            # Absent on a store that has only ever seen availability probes, and
            # `rank` treats absent as "not measured" rather than as "bad".
            "tok_s": float(row["tok_s"] or 0) if "tok_s" in row.keys() else 0.0,
            "json_ok": bool(row["json_ok"]) if "json_ok" in row.keys() else False,
            "samples": samples,
            "failures": failures,
            "reliability": 1.0 if not samples else 1.0 - failures / samples,
        }
    return out


# A verdict is a measurement, and measurements age. A model blocked six months
# ago may be open today, and a `capacity` was never a verdict in the first
# place — it is the one state that is explicitly provisional.
STALE_DAYS = 30


def stale(store, days: int = STALE_DAYS) -> list[tuple[str, str, str]]:
    """(provider, model, state) worth asking again, most provisional first.

    `capacity` leads whatever its age: it means "the provider was busy", which
    is not knowledge and never becomes knowledge by sitting in a table. Then
    anything older than `days`.
    """
    now = time.time()
    provisional, old = [], []
    for row in store.known_probes():
        age = (now - float(row["ts"] or now)) / 86400
        entry = (row["provider"], row["model"], row["state"])
        if row["state"] == CAPACITY:
            provisional.append(entry)
        elif age > days:
            old.append(entry)
    return provisional + old


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

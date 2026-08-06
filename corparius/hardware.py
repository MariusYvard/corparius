"""What this machine can actually run locally.

The routing decided the trivial tier on one bit — did Ollama's port answer — and
then handed that tier a 9.6 GB model. Reachable is not capable: a box with 4 GB
free and no GPU answers `/api/tags` in a millisecond and then takes a minute to
draft one post. And the trivial tier is the *most* frequent in the roster, so it
is the worst place to put a model the machine cannot serve.

Measure, don't infer. That is already the house rule — `integrations.smtp_check`
and `claudecli.check` prove the thing works by making one real minimal call
rather than asking the operator to trust it — and it matters more here than
anywhere: specs predict throughput badly. A 16 GB Mac beats a 64 GB desktop with
no GPU. Specs answer a different, narrower question ("does this model even fit in
memory") and explain *why* a number came out low; they do not decide.

Everything needed is already in the responses corparius makes. Ollama returns
`eval_count` / `eval_duration` (throughput), `load_duration` (cold start), and
`/api/ps` reports `size_vram` against `size` (GPU, partial offload, or CPU only).
`OllamaProvider` was reading two of those fields and dropping the rest — the same
shape of miss as the OpenRouter cost.

Nothing here runs on a polled path. Measurement costs a real generation; it
happens on an explicit operator action and is cached.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time

import requests

from .config import cfg

log = logging.getLogger("corparius.hardware")

# A short, fixed prompt: the measurement must not vary with what the company
# happens to be doing, and a long one would measure prompt evaluation instead of
# generation.
PROBE_PROMPT = "Write one short sentence about coffee."
PROBE_TOKENS = 48

# How much of *total* memory a model may claim before it is judged not to fit.
# Total, not available: available is the weather, not the climate. Measured on
# one machine an hour apart it went from 4.0 GB to 1.9 GB purely because a test
# suite was running, and a fit verdict built on it would have flipped with it.
# Both platforms also under-report what is genuinely reclaimable — page cache is
# not counted as available but is evicted the moment a model needs the room.
FIT_MARGIN = 0.8

# What a draft costs. Tools cap generation at this, so it is the honest
# worst case to quote when explaining a throughput number.
DRAFT_TOKENS = 512


def _base() -> str:
    return cfg.get("CORP_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _windows_memory() -> tuple[int | None, int | None]:
    class _Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    # getattr, not ctypes.windll: the attribute exists only in the Windows
    # stubs, so a direct reference fails mypy on Linux — the same asymmetry as
    # os.sysconf in _posix_memory below, in the other direction. The runtime
    # guard has to be one mypy can check on every platform it runs on.
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None, None
    try:
        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        if not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return int(status.ullTotalPhys), int(status.ullAvailPhys)
    except (OSError, AttributeError, ValueError):
        return None, None


def _posix_memory() -> tuple[int | None, int | None]:
    """Total from SC_PHYS_PAGES, available from SC_AVPHYS_PAGES.

    The second is Linux-only in practice: macOS defines neither reliably, and
    free pages there mean something different anyway because of compression.
    Returning None for it is the honest answer; the caller falls back to total.
    """

    # getattr rather than os.sysconf: the name does not exist on Windows, and
    # typing this module against a Windows stdlib is how the whole file would
    # otherwise fail type-checking on the platform it is not used on.
    sysconf = getattr(os, "sysconf", None)
    if sysconf is None:
        return None, None

    def pages(name: str) -> int | None:
        try:
            value = sysconf(name)
        except (ValueError, OSError, AttributeError):
            return None
        return int(value) if isinstance(value, int) and value > 0 else None

    size = pages("SC_PAGE_SIZE")
    if size is None:
        return None, None
    total, avail = pages("SC_PHYS_PAGES"), pages("SC_AVPHYS_PAGES")
    return (total * size if total else None), (avail * size if avail else None)


def specs() -> dict:
    """Cores and memory, in bytes. Never raises.

    A field is `None` when this platform does not expose it, never 0 — the two
    mean opposite things, and a consumer that treats "I don't know" as "there is
    none" would refuse to run local inference on a machine that could.
    """
    if sys.platform == "win32":
        total, available = _windows_memory()
    else:
        total, available = _posix_memory()
    return {"cores": os.cpu_count(), "ram_total": total, "ram_available": available}


def installed_models(timeout: int = 4) -> list[dict]:
    """Every model Ollama holds, with the size it occupies on disk — which is
    close enough to what it will want in memory to decide whether it fits."""
    try:
        r = requests.get(f"{_base()}/api/tags", timeout=timeout)
        r.raise_for_status()
        models = r.json().get("models") or []
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in models:
        name = str(m.get("name", "")).strip()
        if not name:
            continue
        out.append({"name": name, "size": int(m.get("size") or 0)})
    return sorted(out, key=lambda m: m["size"])


def _placement(model: str, timeout: int = 4) -> str:
    """gpu | partial | cpu | unknown, from the model Ollama has loaded.

    Read after a generation, while the model is still resident: `size_vram` is
    how much of it sits on the GPU. Zero means the CPU is doing all of it, which
    is the single strongest predictor of a machine that should not be serving a
    tier.
    """
    try:
        r = requests.get(f"{_base()}/api/ps", timeout=timeout)
        r.raise_for_status()
        loaded = r.json().get("models") or []
    except (requests.RequestException, ValueError):
        return "unknown"
    for m in loaded:
        if str(m.get("name", "")).split(":")[0] != model.split(":")[0]:
            continue
        size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        if not size:
            return "unknown"
        if vram >= size * 0.95:
            return "gpu"
        return "partial" if vram else "cpu"
    return "unknown"


def measure(model: str, timeout: int = 300) -> dict:
    """One real generation, timed by Ollama itself.

    Returns `{"ok": bool, "detail": str, ...}`. On success it carries
    `tokens_per_second`, `load_seconds`, `placement` and `model`.

    A server that answers without the duration fields yields **no verdict** —
    `ok: False` with a reason — rather than a number derived from a clock this
    process happens to hold. Timing the HTTP round trip instead would fold in
    queueing and the network, and quietly overstate how slow the machine is.
    """
    if not model:
        return {"ok": False, "detail": "no model named"}
    try:
        r = requests.post(
            f"{_base()}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROBE_PROMPT}],
                "stream": False,
                "options": {"num_predict": PROBE_TOKENS},
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        return {"ok": False, "detail": f"Ollama did not answer at {_base()}: {exc}"}
    except ValueError as exc:
        return {"ok": False, "detail": f"Ollama returned something that is not JSON: {exc}"}
    if data.get("error"):
        return {"ok": False, "detail": f"{model}: {data['error']}"}
    return {**parse_timings(data), "model": model, "placement": _placement(model)}


def parse_timings(data: dict) -> dict:
    """Throughput and cold-start from an Ollama chat response.

    Shared by `measure` and by OllamaProvider, so a real turn and a probe read
    the same fields the same way. Missing or zero durations mean no verdict, not
    a division by zero and not an invented one.
    """
    count = int(data.get("eval_count") or 0)
    nanos = int(data.get("eval_duration") or 0)
    if count <= 0 or nanos <= 0:
        return {
            "ok": False,
            "detail": "this Ollama did not report eval_count / eval_duration, so there is "
            "nothing to measure against.",
        }
    return {
        "ok": True,
        "tokens_per_second": round(count / (nanos / 1e9), 1),
        "load_seconds": round(int(data.get("load_duration") or 0) / 1e9, 2),
        "detail": "",
    }


def draft_seconds(tokens_per_second: float) -> float:
    """How long a full-length draft takes at this speed. Quoted alongside every
    verdict: an operator can disagree with a threshold, but not with the
    arithmetic behind it."""
    if tokens_per_second <= 0:
        return 0.0
    return round(DRAFT_TOKENS / tokens_per_second, 1)


def fits(model_size: int, spec: dict | None = None) -> bool | None:
    """Whether a model of this size fits this machine at all.

    Judged against total memory, not free memory. None when the platform did not
    tell us how much there is — unknown is not the same as no, and refusing
    local inference on a machine we merely failed to measure would be wrong.
    """
    spec = spec if spec is not None else specs()
    room = spec.get("ram_total") or spec.get("ram_available")
    if not room or model_size <= 0:
        return None
    return model_size <= room * FIT_MARGIN


def tight(model_size: int, spec: dict | None = None) -> bool | None:
    """Whether loading it right now would have to evict something.

    Separate from `fits` and never used to refuse: it is a fact about this
    moment, not about the machine, and a decision that flips depending on
    whether a test suite happens to be running is not a decision.
    """
    spec = spec if spec is not None else specs()
    free = spec.get("ram_available")
    if not free or model_size <= 0:
        return None
    return model_size > free


def profile(store, max_age_days: int = 30) -> dict | None:
    """The cached measurement, or None when nothing has been measured.

    Never measures. This is what the doctor and the console read, and both are
    called often enough that a probe here would be the polled-endpoint mistake
    all over again. `stale` is reported rather than acted on: a caller deciding
    to re-measure is doing something the operator asked for; silently reusing a
    year-old number, or silently discarding it, are both worse than saying so.
    """
    row = store.load_machine() if store is not None else None
    if not row:
        return None
    age_days = max(0.0, (time.time() - float(row.get("ts") or 0)) / 86400)
    return {**row, "age_days": round(age_days, 1), "stale": age_days > max_age_days}


def verdict(prof: dict | None, model_size: int = 0, min_tokens_per_second: float = 15.0) -> dict:
    """Can this machine serve a tier with a local model?

    Two questions, deliberately answered separately, because they fail for
    different reasons and only one of them needs a measurement:

    - Does it fit? Weights against available memory. This is the case that is
      broken today — a 9.6 GB model recommended onto a box with 4 GB free — and
      it is decided from specs alone, before anything is run.
    - Is it fast enough? Measured throughput against a threshold. The threshold
      is a judgement, so the reason quotes the arithmetic behind it: an operator
      can disagree with a number, not with "at 8.6 tok/s a 512-token draft takes
      60 seconds".
    """
    spec = specs()
    room = spec.get("ram_total") or spec.get("ram_available")
    if model_size and fits(model_size, spec) is False:
        return {
            "ok": False,
            "reason": (
                f"the model needs {model_size / 1e9:.1f} GB and this machine has "
                f"{(room or 0) / 1e9:.1f} GB of memory in total"
            ),
        }
    if not prof:
        return {"ok": False, "reason": "not measured yet; run `corparius bench`"}
    speed = float(prof.get("tokens_per_second") or 0)
    if speed <= 0:
        return {"ok": False, "reason": "the last measurement produced no throughput"}
    if speed < min_tokens_per_second:
        placement = prof.get("placement") or "unknown"
        where = " on the CPU" if placement == "cpu" else ""
        return {
            "ok": False,
            "reason": (
                f"{speed} tokens/s{where}, so a {DRAFT_TOKENS}-token draft takes "
                f"{draft_seconds(speed)}s (threshold {min_tokens_per_second}/s)"
            ),
        }
    return {
        "ok": True,
        "reason": (
            f"{speed} tokens/s, so a {DRAFT_TOKENS}-token draft takes {draft_seconds(speed)}s"
        ),
    }


def profile_save(store, spec: dict, result: dict) -> None:
    """Persist a measurement. One place builds the row, so the CLI and the
    console cannot store two different shapes of the same fact."""
    store.save_machine(
        {
            **spec,
            "tokens_per_second": result.get("tokens_per_second"),
            "load_seconds": result.get("load_seconds"),
            "placement": result.get("placement", ""),
            "model": result.get("model", ""),
        }
    )


def recommended_local(store, settings, models=None) -> tuple[str, str]:
    """The local model this machine should serve the trivial tier with, and why.

    Returns ("", reason) when it should serve none — the caller then routes that
    tier to a free provider. One place decides it, so the console button, the
    CLI and the doctor cannot drift into three different answers.

    Reads the cached measurement and never takes one: this is called from a
    button press and from the doctor, and a probe on either would be the
    polled-endpoint mistake again. `models` lets a caller that has just listed
    them hand the list over rather than pay a second round-trip for it.
    """
    from .config.provider_table import split_target

    prefer = split_target(getattr(settings, "trivial_model", ""))[1]
    prof = profile(store, max_age_days=getattr(settings, "bench_max_age_days", 30))
    models = installed_models() if models is None else models
    if not models:
        return "", "no local model installed, or Ollama is not reachable"
    choice = best_local_model(models, prefer=prefer)
    if not choice:
        return "", "no installed model fits this machine's memory"
    size = next((m["size"] for m in models if m["name"] == choice), 0)
    call = verdict(prof, size, float(getattr(settings, "local_min_tokens_per_second", 15.0)))
    if not call["ok"]:
        return "", call["reason"]
    note = f"{choice}: {call['reason']}"
    if tight(size, specs()):
        note += " (it will have to evict cache to load right now)"
    return choice, note


def best_local_model(candidates=None, prefer: str = "", spec: dict | None = None) -> str:
    """The largest installed model that fits, preferring the configured one.

    Largest-that-fits rather than smallest-that-runs: within what memory allows,
    a bigger model is a better one, and the operator already paid the disk for
    it. Returns "" when nothing fits — which is a real answer, and the one this
    machine gives for a 9.6 GB default against 4 GB free.
    """
    spec = spec if spec is not None else specs()
    models = installed_models() if candidates is None else list(candidates)
    usable = [m for m in models if fits(m["size"], spec) is not False]
    if not usable:
        return ""
    if prefer:
        # Exact name, or the family only when the operator named no tag.
        # Matching on the family alone would answer `gemma4:e4b` with
        # `gemma4:12b` — same family, different model, different size.
        want = prefer.removesuffix(":latest")
        for m in usable:
            if m["name"].removesuffix(":latest") == want:
                return m["name"]
        if ":" not in want:
            for m in usable:
                if m["name"].split(":")[0] == want:
                    return m["name"]
    return max(usable, key=lambda m: m["size"])["name"]

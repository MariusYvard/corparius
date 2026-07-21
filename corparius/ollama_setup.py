"""Ollama from the console: see what is running, pull what is missing.

Ollama is already the local fallback and any `local:` tier, but the operator had
to install it and `ollama pull` each model in a terminal, reading the doctor to
know which. This exposes the status the doctor computes and lets the missing
models be pulled from the page.
"""

from __future__ import annotations

import requests

from . import cfg, i18n
from .config import Settings
from .llm import _split


def _base() -> str:
    return cfg.get("CORP_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def wanted_models(s: Settings | None = None) -> list[str]:
    """Every model the current routing actually needs from Ollama: the local
    tiers, the local fallback and the embedding model."""
    s = s or Settings()
    tiers = [s.trivial_model, s.normal_model, s.hard_model]
    names = {_split(m)[1] for m in tiers if _split(m)[0] == "local"}
    names |= {s.local_model, s.embed_model}
    return sorted(n for n in names if n)


def status(timeout: int = 4, lang="en") -> dict:
    p = lambda en, fr: i18n.pick(lang, en, fr)
    s = Settings()
    want = wanted_models(s)
    try:
        r = requests.get(f"{_base()}/api/tags", timeout=timeout)
        r.raise_for_status()
        have = {m.get("name", "").split(":latest")[0] for m in r.json().get("models", [])}
    except requests.RequestException:
        return {
            "ok": False,
            "reachable": False,
            "url": _base(),
            "wanted": want,
            "present": [],
            "missing": want,
            "detail": p(
                f"Ollama is not reachable at {_base()}. Install it from "
                "ollama.com, or point CORP_OLLAMA_URL at your server.",
                f"Ollama est injoignable à {_base()}. Installez-le depuis "
                "ollama.com, ou pointez CORP_OLLAMA_URL vers votre serveur.",
            ),
        }
    missing = [w for w in want if w not in have and w.split(":")[0] not in have]
    present = [w for w in want if w not in missing]
    detail = p(
        f"Reachable at {_base()}, {len(have)} model(s) installed."
        + (
            f" Missing for your tiers: {', '.join(missing)}."
            if missing
            else " Every model your tiers need is present."
        ),
        f"Joignable à {_base()}, {len(have)} modèle(s) installé(s)."
        + (
            f" Manquants pour vos tiers : {', '.join(missing)}."
            if missing
            else " Tous les modèles dont vos tiers ont besoin sont présents."
        ),
    )
    return {
        "ok": not missing,
        "reachable": True,
        "url": _base(),
        "wanted": want,
        "present": present,
        "missing": missing,
        "detail": detail,
    }


def pull(model: str, on_line=None, timeout: int = 3600) -> dict:
    """Pull one model, streaming Ollama's progress. on_line(status_text) is
    called as it goes so a caller can surface progress. Blocking; run it in a
    thread."""
    if not model:
        return {"ok": False, "detail": "no model named"}
    try:
        with requests.post(
            f"{_base()}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            import json as _json

            last = ""
            for raw in r.iter_lines():
                if not raw:
                    continue
                try:
                    msg = _json.loads(raw)
                except ValueError:
                    continue
                if msg.get("error"):
                    return {"ok": False, "detail": f"{model}: {msg['error']}"}
                last = msg.get("status", last)
                if on_line:
                    on_line(f"{model}: {last}")
            return {"ok": True, "detail": f"{model}: {last or 'pulled'}"}
    except requests.RequestException as exc:
        return {"ok": False, "detail": f"Could not pull {model}: {exc}"}

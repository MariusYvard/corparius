"""Preflight diagnostics. Each check returns (level, name, message) where level
is "ok", "warn" or "fail". The CLI prints them; the console serves them as
JSON. Messages always say what to do next, not just what is wrong."""
from __future__ import annotations
import os
import shutil
import socket
import sys
from pathlib import Path

import requests

from .config import Settings
from .llm import OPENAI_COMPAT_PROVIDERS, _split

ROOT = Path(__file__).resolve().parent.parent


def _check_python() -> tuple:
    v = sys.version_info
    if v < (3, 10):
        return ("fail", "python", f"{v.major}.{v.minor} found; corparius needs 3.10+. Install a newer Python.")
    return ("ok", "python", f"{v.major}.{v.minor}.{v.micro}")


def _check_env_file() -> tuple:
    if (ROOT / ".env").is_file():
        return ("ok", ".env", "present")
    return ("warn", ".env", "missing; run `cp .env.example .env` (start.py does it for you). Environment variables still apply.")


def _check_companies() -> tuple:
    base = ROOT / "companies"
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    if slugs:
        return ("ok", "companies", ", ".join(slugs))
    return ("warn", "companies", "none found; create one from the console (New company) or copy companies/example.")


def _check_store(s: Settings) -> tuple:
    try:
        os.makedirs(s.data_path, exist_ok=True)
        probe = Path(s.data_path) / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        return ("ok", "store", f"writable at {s.data_path}")
    except OSError as exc:
        return ("fail", "store", f"cannot write {s.data_path}: {exc}. Fix permissions or set CORP_DATA_PATH.")


def _check_mode(s: Settings) -> tuple:
    if s.llm_mock:
        return ("ok", "mode", "mock (offline, deterministic). Flip CORP_LLM_MOCK=false to go live.")
    if not s.cloud_enabled:
        return ("ok", "mode", "live, local-only (cloud gate closed). Ollama serves every tier.")
    return ("ok", "mode", "live with remote providers enabled")


def _check_ollama(s: Settings) -> tuple:
    tiers = [s.trivial_model, s.normal_model, s.hard_model]
    needs_local = s.llm_mock is False and (
        any(_split(m)[0] == "local" for m in tiers) or True)  # local is always the fallback
    try:
        r = requests.get(f"{s.ollama_url.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        have = {m.get("name", "").split(":latest")[0] for m in r.json().get("models", [])}
        wanted = {_split(m)[1] for m in tiers if _split(m)[0] == "local"} | {s.local_model, s.embed_model}
        missing = {w for w in wanted if w and w not in have and w.split(":")[0] not in have}
        if missing:
            pulls = " && ".join(f"ollama pull {m}" for m in sorted(missing))
            return ("warn", "ollama", f"reachable, but missing models: {', '.join(sorted(missing))}. Run: {pulls}")
        return ("ok", "ollama", f"reachable at {s.ollama_url}, {len(have)} models")
    except requests.RequestException:
        level = "warn" if s.llm_mock else ("fail" if needs_local else "warn")
        return (level, "ollama",
                f"not reachable at {s.ollama_url}. Install from ollama.com or set CORP_OLLAMA_URL. "
                "Mock mode works without it; live mode needs it as the local fallback.")


def _check_providers(s: Settings) -> tuple:
    keyed = [n for n, spec in OPENAI_COMPAT_PROVIDERS.items()
             if os.environ.get(spec["key_env"], "").strip()]
    anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if s.llm_mock:
        return ("ok", "providers", "mock mode; keys are not used yet")
    if not s.cloud_enabled:
        return ("ok", "providers", "cloud gate closed; running fully on-prem")
    total = len(keyed) + (1 if anthropic else 0) + (1 if s.claude_code_enabled else 0)
    if total == 0:
        return ("warn", "providers",
                "cloud is enabled but no key is set; remote tiers will fall back to local. "
                "Paste a free key in the console (Providers tab), e.g. Groq.")
    names = keyed + (["anthropic"] if anthropic else []) + (["claudecode"] if s.claude_code_enabled else [])
    return ("ok", "providers", f"{total} active: {', '.join(names)}")


def _check_network(s: Settings) -> tuple:
    if s.llm_mock or not s.cloud_enabled:
        return ("ok", "network", "not needed in the current mode")
    try:
        socket.getaddrinfo("api.groq.com", 443)
        return ("ok", "network", "outbound DNS resolves")
    except OSError:
        return ("fail", "network", "cannot resolve api.groq.com; check your connection, DNS or proxy.")


def _check_claude_cli(s: Settings) -> tuple:
    if not s.claude_code_enabled:
        return ("ok", "claude cli", "disabled (CORP_CLAUDE_CODE=false)")
    if shutil.which("claude"):
        return ("ok", "claude cli", "found on PATH")
    return ("fail", "claude cli", "CORP_CLAUDE_CODE=true but the `claude` CLI is not on PATH. Install Claude Code and log in.")


def run_checks(settings: Settings | None = None) -> list[dict]:
    s = settings or Settings()
    checks = [_check_python(), _check_env_file(), _check_mode(s), _check_store(s),
              _check_companies(), _check_ollama(s), _check_providers(s),
              _check_network(s), _check_claude_cli(s)]
    return [{"level": lv, "name": n, "message": m} for lv, n, m in checks]


def main(quiet: bool = False) -> int:
    results = run_checks()
    worst = "ok"
    icon = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
    for r in results:
        if not quiet or r["level"] != "ok":
            print(f"{icon[r['level']]} {r['name']:<10} {r['message']}")
        if r["level"] == "fail" or (r["level"] == "warn" and worst == "ok"):
            worst = r["level"]
    if not quiet:
        print({"ok": "\nAll green. Run the console: python -m app.cli ui",
               "warn": "\nUsable with warnings; the messages above say what to improve.",
               "fail": "\nSomething blocking needs a fix; see the FAIL lines above."}[worst])
    return 1 if worst == "fail" else 0

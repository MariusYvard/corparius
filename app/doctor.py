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

from . import cfg, paths
from .config import Settings
from .llm import OPENAI_COMPAT_PROVIDERS, _split

ROOT = Path(__file__).resolve().parent.parent


def _check_python() -> tuple:
    v = sys.version_info
    if v < (3, 10):
        return ("fail", "python", f"{v.major}.{v.minor} found; corparius needs 3.10+. Install a newer Python.")
    return ("ok", "python", f"{v.major}.{v.minor}.{v.micro}")


def _check_env_file() -> tuple:
    path = cfg.dotenv_path()
    if not path.is_file():
        return ("warn", ".env",
                "missing; run `cp .env.example .env` (start.py does it for you). "
                "Settings saved from the console and real environment variables still apply.")
    try:
        count = len(cfg.parse_dotenv(path.read_text(encoding="utf-8")))
    except OSError as exc:
        return ("fail", ".env", f"cannot read {path}: {exc}. Fix permissions.")
    return ("ok", ".env",
            f"loaded, {count} variables. Lowest precedence: the process environment "
            "and settings saved from the console both override it.")


def _check_settings_source(s: Settings) -> tuple:
    """Console settings that the process environment overrides. Silently losing
    an operator's saved value is the one thing this layering must never do."""
    try:
        from .store import Store
        stored = Store(s.data_path).all_settings()
    except Exception:
        return ("ok", "settings", "no settings saved from the console yet")
    if not stored:
        return ("ok", "settings", "no settings saved from the console yet")
    shadowed = sorted(k for k in stored if os.environ.get(k) is not None)
    if shadowed:
        return ("warn", "settings",
                f"{len(stored)} saved from the console, but the environment overrides "
                f"{', '.join(shadowed)}. The console shows these as read-only. "
                "Unset them in your shell or compose file to edit them from the page.")
    return ("ok", "settings", f"{len(stored)} saved from the console, all in effect")


def _check_exposure(s: Settings) -> tuple:
    """A console bound off-localhost with no token is an open remote control:
    it can spend money, publish a site and read every key's status."""
    local = {"127.0.0.1", "localhost", "::1"}
    if s.ui_host in local:
        return ("ok", "exposure", f"console bound to {s.ui_host} (localhost only)")
    if s.ui_token.strip():
        return ("ok", "exposure", f"console on {s.ui_host}, token required")
    return ("fail", "exposure",
            f"console bound to {s.ui_host} with no CORP_UI_TOKEN. Anyone who can reach "
            "it can spend money and publish. Set CORP_UI_TOKEN, or bind 127.0.0.1.")


def _check_secrets_at_rest(s: Settings) -> tuple:
    from . import secretbox
    db = Path(s.data_path) / "corparius.sqlite"
    if not db.is_file():
        return ("ok", "secrets", "no store yet")
    if secretbox.enabled() and not secretbox.available():
        return ("fail", "secrets", secretbox._INSTALL_HINT)
    if secretbox.enabled():
        return ("ok", "secrets",
                "encrypted at rest (CORP_SECRET_KEY set). Keep the passphrase safe: "
                "lose it and the stored secrets cannot be recovered.")
    note = ("API keys saved from the console are stored in the clear in "
            f"{db}, and `cli.py backup` includes them in the zip. Set CORP_SECRET_KEY "
            "to encrypt them at rest (see docs/securite.md).")
    if os.name != "nt":
        mode = db.stat().st_mode & 0o077
        if mode:
            return ("warn", "secrets", f"{note} It is also readable beyond its owner; run: chmod 600 {db}")
    return ("ok", "secrets", note)


def _check_companies() -> tuple:
    base = paths.companies_dir()
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
             if cfg.get(spec["key_env"], "").strip()]
    anthropic = bool(cfg.get("ANTHROPIC_API_KEY", "").strip())
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
        # Whether it is logged in needs a real call, which the doctor will not
        # spend a subscription message on; the console's Test button does that.
        return ("ok", "claude cli", "found on PATH. Test the login from the console (Providers).")
    return ("fail", "claude cli",
            "CORP_CLAUDE_CODE=true but the `claude` CLI is not on PATH. Install Claude Code, "
            "run `claude login`, or turn it off from the console (Providers).")


def _check_deploy_order() -> tuple:
    """The local provider is always available, so anything ordered after it is
    unreachable. Setting NETLIFY_AUTH_TOKEN and expecting a publish is the
    footgun this catches."""
    from . import deploy as deploy_mod
    order = cfg.get_csv("CORP_DEPLOY_PROVIDERS", "local,netlify,s3,ssh")
    unknown = [n for n in order if n not in deploy_mod.REGISTRY]
    if unknown:
        return ("warn", "deploy", f"unknown provider(s) in CORP_DEPLOY_PROVIDERS: {', '.join(unknown)}")
    if "local" not in order:
        return ("ok", "deploy", f"order: {', '.join(order)}")
    after = order[order.index("local") + 1:]
    reachable = [n for n in after if deploy_mod.REGISTRY[n].available()]
    if reachable:
        return ("warn", "deploy",
                f"'local' is ordered before {', '.join(reachable)} and is always available, "
                f"so it always wins and {', '.join(reachable)} will never run. "
                f"Set CORP_DEPLOY_PROVIDERS={','.join(reachable + ['local'])} to publish there.")
    return ("ok", "deploy", f"order: {', '.join(order)}")


def run_checks(settings: Settings | None = None) -> list[dict]:
    s = settings or Settings()
    checks = [_check_python(), _check_env_file(), _check_settings_source(s),
              _check_mode(s), _check_exposure(s), _check_store(s),
              _check_secrets_at_rest(s), _check_companies(), _check_ollama(s),
              _check_providers(s), _check_network(s), _check_claude_cli(s),
              _check_deploy_order()]
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

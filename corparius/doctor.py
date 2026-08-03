"""Preflight diagnostics. Each check returns (level, name, message) where level
is "ok", "warn" or "fail". The CLI prints them; the console serves them as
JSON. Messages always say what to do next, not just what is wrong."""

from __future__ import annotations

import os
import shutil
import socket
import sys
import time
from pathlib import Path

import requests

from . import cfg, paths, permissions
from .config import Settings
from .llm import OPENAI_COMPAT_PROVIDERS, _split, list_models
from .store import SCHEMA_VERSION, Store

ROOT = Path(__file__).resolve().parent.parent


def _check_python() -> tuple:
    v = sys.version_info
    if v < (3, 10):
        return (
            "fail",
            "python",
            f"{v.major}.{v.minor} found; corparius needs 3.10+. Install a newer Python.",
        )
    return ("ok", "python", f"{v.major}.{v.minor}.{v.micro}")


def _check_env_file() -> tuple:
    path = cfg.dotenv_path()
    if not path.is_file():
        return (
            "warn",
            ".env",
            "missing; run `cp .env.example .env` (start.py does it for you). "
            "Settings saved from the console and real environment variables still apply.",
        )
    try:
        count = len(cfg.parse_dotenv(path.read_text(encoding="utf-8")))
    except OSError as exc:
        return ("fail", ".env", f"cannot read {path}: {exc}. Fix permissions.")
    return (
        "ok",
        ".env",
        f"loaded, {count} variables. Lowest precedence: the process environment "
        "and settings saved from the console both override it.",
    )


def _check_settings_source(s: Settings, store: Store | None) -> tuple:
    """Console settings that the process environment overrides. Silently losing
    an operator's saved value is the one thing this layering must never do."""
    if store is None:
        return ("ok", "settings", "no store yet to read saved settings from")
    try:
        stored = store.all_settings()
    except Exception:  # noqa: BLE001 - an unreadable store has its own check
        return ("ok", "settings", "no settings saved from the console yet")
    if not stored:
        return ("ok", "settings", "no settings saved from the console yet")
    shadowed = sorted(k for k in stored if os.environ.get(k) is not None)
    if shadowed:
        return (
            "warn",
            "settings",
            f"{len(stored)} saved from the console, but the environment overrides "
            f"{', '.join(shadowed)}. The console shows these as read-only. "
            "Unset them in your shell or compose file to edit them from the page.",
        )
    return ("ok", "settings", f"{len(stored)} saved from the console, all in effect")


def _check_exposure(s: Settings) -> tuple:
    """A console bound off-localhost with no token is an open remote control:
    it can spend money, publish a site and read every key's status."""
    from . import cfg

    local = {"127.0.0.1", "localhost", "::1"}
    allowed = [h.strip() for h in cfg.get("CORP_UI_ALLOWED_HOSTS", "").split(",") if h.strip()]
    hosts = f", Host limited to {', '.join(allowed)}" if allowed else ""
    if s.ui_host in local:
        return ("ok", "exposure", f"console bound to {s.ui_host} (localhost only){hosts}")
    if s.ui_token.strip():
        # Off-loopback with a token is authenticated, but the Host allow-list is
        # what stops a rebound DNS name from reaching it, and off-loopback is
        # exactly where that is not inferable.
        if not allowed:
            return (
                "warn",
                "exposure",
                f"console on {s.ui_host}, token required, but CORP_UI_ALLOWED_HOSTS "
                "is unset so any Host header is accepted. Set it to the name you "
                "serve the console under.",
            )
        return ("ok", "exposure", f"console on {s.ui_host}, token required{hosts}")
    return (
        "fail",
        "exposure",
        f"console bound to {s.ui_host} with no CORP_UI_TOKEN. Anyone who can reach "
        "it can spend money and publish. Set CORP_UI_TOKEN, or bind 127.0.0.1.",
    )


def _check_secrets_at_rest(s: Settings) -> tuple:
    from . import secretbox

    db = Path(s.data_path) / "corparius.sqlite"
    if not db.is_file():
        return ("ok", "secrets", "no store yet")
    if secretbox.enabled() and not secretbox.available():
        return ("fail", "secrets", secretbox._INSTALL_HINT)
    if secretbox.enabled():
        return (
            "ok",
            "secrets",
            "encrypted at rest (CORP_SECRET_KEY set). Backups carry them as "
            "ciphertext, so they restore in full. Keep the passphrase safe: "
            "lose it and the stored secrets cannot be recovered.",
        )
    note = (
        "API keys saved from the console are stored in the clear in "
        f"{db}. Backups blank them rather than carry them, so a restore needs "
        "them typed back in; set CORP_SECRET_KEY to encrypt them at rest and "
        "have backups restore in full (see docs/securite.md)."
    )
    if os.name != "nt":
        mode = db.stat().st_mode & 0o077
        if mode:
            return (
                "warn",
                "secrets",
                f"{note} It is also readable beyond its owner; run: chmod 600 {db}",
            )
    return ("ok", "secrets", note)


def _check_plugins(s: Settings) -> tuple:
    if not cfg.get_bool("CORP_PLUGINS_ENABLED"):
        return ("ok", "plugins", "off (CORP_PLUGINS_ENABLED=false)")
    from . import plugins

    st = plugins.status()
    unverified = [p["name"] for p in st["installed"] if p["loaded"] and not p["verified"]]
    if unverified:
        return (
            "warn",
            "plugins",
            f"{len(st['loaded'])} loaded, including UNVERIFIED: {', '.join(unverified)}. "
            "Unverified plugins run unaudited third-party code.",
        )
    return ("ok", "plugins", f"on; {len(st['installed'])} installed, {len(st['loaded'])} loaded")


def _check_companies() -> tuple:
    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    if slugs:
        return ("ok", "companies", ", ".join(slugs))
    return (
        "warn",
        "companies",
        "none found; create one from the console (New company) or copy companies/example.",
    )


def _check_store(s: Settings, store: Store | None) -> tuple:
    try:
        os.makedirs(s.data_path, exist_ok=True)
        probe = Path(s.data_path) / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return (
            "fail",
            "store",
            f"cannot write {s.data_path}: {exc}. Fix permissions or set CORP_DATA_PATH.",
        )
    # A store a newer build migrated, opened by an older one. It still opens —
    # rolling back is the recovery path when an update goes wrong — but running
    # on it can write values a later schema means differently, and nothing else
    # would ever say so.
    if store is None:
        return ("fail", "store", f"{s.data_path} is writable, but no store will open there")
    try:
        found = store.schema_version()
    except Exception:  # noqa: BLE001 - the writability answer above still stands
        return ("ok", "store", f"writable at {s.data_path}")
    if found > SCHEMA_VERSION:
        return (
            "fail",
            "store",
            f"this store was written by a newer corparius (schema {found}; this build "
            f"knows {SCHEMA_VERSION}). Update again, or restore the backup taken before "
            "the update. Running an older build against it can write values the newer "
            "schema means differently.",
        )
    return ("ok", "store", f"writable at {s.data_path}")


def _check_mode(s: Settings) -> tuple:
    if s.llm_mock:
        return ("ok", "mode", "mock (offline, deterministic). Flip CORP_LLM_MOCK=false to go live.")
    if not s.cloud_enabled:
        return ("ok", "mode", "live, local-only (cloud gate closed). Ollama serves every tier.")
    return ("ok", "mode", "live with remote providers enabled")


def _check_permissions(s: Settings) -> tuple:
    """The posture, stated plainly. The dangerous configuration is not an
    invalid one, it is a coherent one the operator forgot they chose: `auto`
    against live providers means only the three named tools ever ask."""
    mode = s.permission_mode if s.permission_mode in permissions.MODES else ""
    if not mode:
        return (
            "fail",
            "permissions",
            f"CORP_PERMISSION_MODE={s.permission_mode!r} is not one of "
            f"{', '.join(permissions.MODES)}; interactive applies instead.",
        )
    if s.ask_above not in permissions.ORDER:
        return (
            "fail",
            "permissions",
            f"CORP_ASK_ABOVE={s.ask_above!r} is not a risk class "
            f"({', '.join(permissions.RISK_CLASSES)}); {permissions.DEFAULT_ASK_ABOVE} applies.",
        )
    gated = ", ".join(s.hitl_tools) or "nothing"
    if mode == permissions.AUTO and not s.llm_mock:
        return (
            "warn",
            "permissions",
            f"auto mode against live providers: only {gated} will ever ask. "
            "Set CORP_PERMISSION_MODE=interactive to restore the gate.",
        )
    if mode == permissions.CUSTOM and not s.auto_allow:
        return (
            "warn",
            "permissions",
            "custom mode with an empty CORP_AUTO_ALLOW behaves exactly like interactive.",
        )
    if mode == permissions.DISCUSS:
        return ("ok", "permissions", "discuss (dry run): nothing consequential executes.")
    return ("ok", "permissions", f"{mode}, asks above {s.ask_above}; gated by name: {gated}")


def _check_budgets(s: Settings) -> tuple:
    """A per-minute ceiling too low to run a turn freezes the day, every day.

    Measured: a company declaring 8000 froze six times in one session, and the
    log said the circuit breaker tripped without saying which ceiling. The value
    is the operator's to choose — two tests set a tiny one deliberately to trip
    the breaker — so it is reported here rather than overridden. One real turn of
    one agent is three or four calls of about a thousand tokens, and several
    agents land in the same wall-clock minute.
    """
    from . import company as company_mod

    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    thin = []
    for slug in slugs:
        try:
            cfg_c = company_mod.load(base / slug / "company.yaml", slug)
        except (FileNotFoundError, ValueError):
            continue
        tpm = int((cfg_c.get("budgets") or {}).get("tokens_per_minute", 0) or 0)
        if 0 < tpm < 20_000:
            thin.append(f"{slug} ({tpm})")
    if not thin:
        return ("ok", "budgets", f"{len(slugs)} company(ies), none with a ceiling too low to run")
    return (
        "warn",
        "budgets",
        f"budgets.tokens_per_minute is too low to run a real turn in: {', '.join(thin)}. "
        "The circuit breaker will freeze the day. Raise it to 20000 or more in "
        "company.yaml, or from the console's company editor.",
    )


def _check_apps(s: Settings) -> tuple:
    """What the company would serve, and to whom.

    The failure worth naming is an app with no key set: it is defined, it looks
    ready, and every call to it is refused. The next one is an app with no
    origin list, which no browser can call — correct as a default and the
    likeliest thing to be mistaken for a bug.
    """
    from . import apps as apps_mod
    from . import cfg
    from .appserver import key_env

    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    defined = [(slug, app) for slug in slugs for app in apps_mod.load(slug)]
    if not defined:
        return ("ok", "apps", "none defined")
    on = cfg.get_bool("CORP_APPS_ENABLED")
    head = f"{len(defined)} app(s) across {len({s for s, _ in defined})} company(ies)"
    if not on:
        return ("ok", "apps", f"{head}; the endpoint is off (CORP_APPS_ENABLED=false)")
    keyless = [f"{slug}/{a.name}" for slug, a in defined if not cfg.get(key_env(slug, a.name), "")]
    if keyless:
        return (
            "warn",
            "apps",
            f"{head}, served on {cfg.get('CORP_APPS_HOST', '127.0.0.1')}. No key set for "
            f"{', '.join(keyless)} — every call to those is refused. "
            "Run `corparius apps key <name> --company <slug>`.",
        )
    browserless = [f"{slug}/{a.name}" for slug, a in defined if not a.origins]
    where = cfg.get("CORP_APPS_HOST", "127.0.0.1")
    note = f"{head}, served on {where}"
    if browserless:
        note += f". No origin listed for {', '.join(browserless)}, so no browser can call them"
    return ("ok", "apps", note)


def _check_site(s: Settings) -> tuple:
    """The one SEO fact the generator cannot work out for itself.

    Canonical link, `og:url`, `sitemap.xml` and `robots.txt` all need the
    absolute address the page will live at, and guessing one is worse than
    having none — a canonical pointing at the wrong host tells a crawler to
    index somebody else. So they are simply omitted, silently, which is exactly
    the kind of missing thing an operator never discovers. This says it once.
    """
    from . import company as company_mod

    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    if not slugs:
        return ("ok", "site", "no company yet")
    missing = []
    for slug in slugs:
        cfg, _, _ = company_mod.validate(company_mod.load(company_mod.path_for(slug), slug))
        if not (cfg.get("site") or {}).get("url"):
            missing.append(slug)
    if not missing:
        return ("ok", "site", f"{len(slugs)} company(ies), every one with a site.url")
    return (
        "warn",
        "site",
        f"No site.url for {', '.join(missing)}. The generated page still builds, but with no "
        "canonical link, no og:url, no sitemap.xml and no robots.txt — set it to the address "
        "the page is hosted at once you have deployed it.",
    )


def _check_skills(s: Settings) -> tuple:
    """A skill that names a tool nobody has never applies, and does so silently:
    it is read, parsed and then matched against a name that does not exist. That
    is the one failure the operator cannot see from the console."""
    if not s.skills_enabled:
        return ("ok", "skills", "off (CORP_SKILLS_ENABLED=false)")
    from . import skills as skills_mod
    from .tools import TOOLS

    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    found: dict[str, skills_mod.Skill] = {}
    for slug in slugs or [""]:
        for skill in skills_mod.SkillLoader.for_company(slug).skills:
            found[f"{skill.scope}/{skill.name}"] = skill
    if not found:
        return (
            "ok",
            "skills",
            "none written yet; copy packaging/skill-template into "
            "companies/<slug>/skills/ to teach a company its own trade.",
        )
    unknown = sorted(
        f"{s_.name}:{t}" for s_ in found.values() for t in s_.allowed_tools if t not in TOOLS
    )
    if unknown:
        return (
            "warn",
            "skills",
            f"{len(found)} loaded, but these name a tool that does not exist and so never "
            f"apply: {', '.join(unknown)}.",
        )
    # Two silent failures, both easy to create by copying a skill written for
    # another host: one that names no tool applies to every prompt of every
    # agent, and one longer than the cap is cut without the operator being told.
    unscoped = [f"{s_.name} ({len(s_.instructions)} chars)" for s_ in found.values() if s_.unscoped]
    over = [
        f"{s_.name} ({len(s_.instructions)} > {s.skill_max_chars})"
        for s_ in found.values()
        if len(s_.instructions) > s.skill_max_chars
    ]
    if over:
        return (
            "warn",
            "skills",
            f"{len(found)} loaded; truncated in every prompt that uses them: {', '.join(over)}. "
            "Shorten them, or raise CORP_SKILL_MAX_CHARS.",
        )
    if unscoped:
        always_on = sum(len(s_.instructions) for s_ in found.values() if s_.unscoped)
        return (
            "warn",
            "skills",
            f"{len(found)} loaded, but {', '.join(unscoped)} declare no allowed-tools, so "
            f"{always_on} characters ride on every prompt of every agent. Name the tools they "
            "belong to unless they really are background knowledge.",
        )
    return ("ok", "skills", f"{len(found)} loaded across {len(slugs) or 1} company(ies)")


def _check_inbox(s: Settings, store: Store | None) -> tuple:
    """A company stopped on an unanswered question looks, from every automated
    angle, exactly like a company with nothing to do. The doctor is where an
    operator asks "is anything wrong", so it has to be one of the answers."""
    if store is None:
        return ("ok", "inbox", "no store yet")
    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    questions, notices = 0, 0
    for slug in slugs:
        for item in store.list_inbox(slug, "pending"):
            if item["kind"] == "question":
                questions += 1
            else:
                notices += 1
    if questions:
        return (
            "warn",
            "inbox",
            f"{questions} unanswered question(s) holding work. Run `corparius inbox "
            "--company <slug>`, or answer from the console.",
        )
    if notices:
        return ("warn", "inbox", f"{notices} notice(s) waiting to be read")
    return ("ok", "inbox", "nothing waiting on you")


def _check_memory(s: Settings, store: Store | None) -> tuple:
    if not s.memory_enabled:
        return ("ok", "memory", "off (CORP_MEMORY_ENABLED=false)")
    if s.memory_top_k <= 0:
        return (
            "warn",
            "memory",
            "on, but CORP_MEMORY_TOP_K is 0, so nothing is ever recalled. Agents write "
            "facts nobody reads back.",
        )
    if store is None:
        return ("ok", "memory", "no store yet")
    base = paths.companies_dir()
    slugs = sorted(p.parent.name for p in base.glob("*/company.yaml")) if base.is_dir() else []
    total = sum(len(store.list_memory(slug)) for slug in slugs)
    return (
        "ok",
        "memory",
        f"{total} fact(s) stored, {s.memory_top_k} recalled per prompt, capped at {s.memory_max}",
    )


def _check_machine(s: Settings, store: Store | None) -> tuple:
    """What this machine measured, and what it implies.

    Reads the cache and never measures. A measurement costs a real generation —
    93 seconds to load the configured model on the box this was written for —
    and the doctor is run on every launcher start and served over HTTP. Probing
    here would be the polled-endpoint mistake with a much bigger timer.
    """
    from . import hardware

    spec = hardware.specs()
    cores = spec["cores"] or "?"
    ram = f"{spec['ram_total'] / 1e9:.1f} GB" if spec["ram_total"] else "unknown RAM"
    if store is None:
        return ("ok", "machine", f"{cores} cores, {ram}; no store yet to read a measurement from")
    prof = hardware.profile(store, max_age_days=s.bench_max_age_days)
    if not prof:
        return (
            "ok",
            "machine",
            f"{cores} cores, {ram}. Local speed not measured yet; run `corparius bench` to "
            "find out whether this machine should serve a tier.",
        )
    speed, placement = prof.get("tokens_per_second") or 0, prof.get("placement") or "?"
    age = f", measured {prof['age_days']:.0f} day(s) ago" if prof["age_days"] >= 1 else ""
    head = f"{cores} cores, {ram}; {speed} tokens/s on the {placement.upper()}{age}"
    if prof["stale"]:
        return (
            "warn",
            "machine",
            f"{head}. That measurement is older than {s.bench_max_age_days} days — memory and "
            "installed models move even when speed does not. Re-run `corparius bench`.",
        )
    choice, why = hardware.recommended_local(store, s)
    if choice:
        return ("ok", "machine", f"{head}. Local can serve the trivial tier ({why}).")
    return ("ok", "machine", f"{head}. Local is fallback only: {why}.")


def _check_ollama(s: Settings) -> tuple:
    tiers = [s.trivial_model, s.normal_model, s.hard_model]
    needs_local = s.llm_mock is False and (
        any(_split(m)[0] == "local" for m in tiers) or True
    )  # local is always the fallback
    try:
        r = requests.get(f"{s.ollama_url.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        have = {m.get("name", "").split(":latest")[0] for m in r.json().get("models", [])}
        wanted = {_split(m)[1] for m in tiers if _split(m)[0] == "local"} | {
            s.local_model,
            s.embed_model,
        }
        missing = {w for w in wanted if w and w not in have and w.split(":")[0] not in have}
        if missing:
            pulls = " && ".join(f"ollama pull {m}" for m in sorted(missing))
            return (
                "warn",
                "ollama",
                f"reachable, but missing models: {', '.join(sorted(missing))}. Run: {pulls}",
            )
        from . import hardware

        # A model bigger than the machine will never load, however reachable
        # Ollama is. Answered from specs alone — no measurement needed.
        for tier in tiers:
            target, name = _split(tier)
            if target != "local" or not name:
                continue
            size = next(
                (m["size"] for m in hardware.installed_models() if m["name"].startswith(name)), 0
            )
            if size and hardware.fits(size) is False:
                total = (hardware.specs()["ram_total"] or 0) / 1e9
                return (
                    "warn",
                    "ollama",
                    f"reachable, but {name} needs {size / 1e9:.1f} GB and this machine has "
                    f"{total:.1f} GB of memory in total. Pick a smaller model.",
                )
        return ("ok", "ollama", f"reachable at {s.ollama_url}, {len(have)} models")
    except requests.RequestException:
        level = "warn" if s.llm_mock else ("fail" if needs_local else "warn")
        return (
            level,
            "ollama",
            f"not reachable at {s.ollama_url}. Install from ollama.com or set CORP_OLLAMA_URL. "
            "Mock mode works without it; live mode needs it as the local fallback.",
        )


def _check_providers(s: Settings) -> tuple:
    keyed = [
        n for n, spec in OPENAI_COMPAT_PROVIDERS.items() if cfg.get(spec["key_env"], "").strip()
    ]
    anthropic = bool(cfg.get("ANTHROPIC_API_KEY", "").strip())
    if s.llm_mock:
        return ("ok", "providers", "mock mode; keys are not used yet")
    if not s.cloud_enabled:
        return ("ok", "providers", "cloud gate closed; running fully on-prem")
    total = len(keyed) + (1 if anthropic else 0) + (1 if s.claude_code_enabled else 0)
    if total == 0:
        return (
            "warn",
            "providers",
            "cloud is enabled but no key is set; remote tiers will fall back to local. "
            "Paste a free key in the console (Providers tab), e.g. Groq.",
        )
    names = (
        keyed
        + (["anthropic"] if anthropic else [])
        + (["claudecode"] if s.claude_code_enabled else [])
    )
    return ("ok", "providers", f"{total} active: {', '.join(names)}")


def _check_network(s: Settings) -> tuple:
    if s.llm_mock or not s.cloud_enabled:
        return ("ok", "network", "not needed in the current mode")
    try:
        socket.getaddrinfo("api.groq.com", 443)
        return ("ok", "network", "outbound DNS resolves")
    except OSError:
        return (
            "fail",
            "network",
            "cannot resolve api.groq.com; check your connection, DNS or proxy.",
        )


def _check_claude_cli(s: Settings) -> tuple:
    if not s.claude_code_enabled:
        # The discovery case. Someone with a Claude subscription and the CLI
        # already installed is paying for inference they could be getting from
        # a login they already have, and the old message ("disabled") told them
        # nothing. The doctor is where an operator asks what is wrong, so it is
        # also the right place to say what is available.
        if shutil.which("claude"):
            return (
                "ok",
                "claude cli",
                "off, but the `claude` CLI is installed here. `corparius claude` points every "
                "tier at your subscription — no API key, no credits.",
            )
        from . import claudecli

        if claudecli.desktop_installed():
            # Having Claude Desktop reads as "already installed" to anyone who
            # has not been told they are two products. Naming it here is the
            # difference between a one-command fix and concluding corparius is
            # broken.
            return (
                "ok",
                "claude cli",
                "off. Claude Desktop is installed but that is the chat app; the Claude Code "
                "CLI is a separate install on the same subscription. "
                "`corparius claude --install` does it and turns this on.",
            )
        return ("ok", "claude cli", "disabled (CORP_CLAUDE_CODE=false)")
    if shutil.which("claude"):
        # Whether it is logged in needs a real call, which the doctor will not
        # spend a subscription message on; the console's Test button does that.
        return ("ok", "claude cli", "found on PATH. Test the login from the console (Providers).")
    from . import claudecli

    desktop = (
        " Claude Desktop is installed, but that is the chat app, not this CLI."
        if claudecli.desktop_installed()
        else ""
    )
    return (
        "fail",
        "claude cli",
        f"CORP_CLAUDE_CODE=true but the `claude` CLI is not on PATH.{desktop} Run "
        "`corparius claude --install`, or turn it off from the console (Providers).",
    )


def _check_deploy_order() -> tuple:
    """The local provider is always available, so anything ordered after it is
    unreachable. Setting NETLIFY_AUTH_TOKEN and expecting a publish is the
    footgun this catches."""
    from . import deploy as deploy_mod

    order = cfg.get_csv("CORP_DEPLOY_PROVIDERS", "local,netlify,s3,ssh")
    unknown = [n for n in order if n not in deploy_mod.REGISTRY]
    if unknown:
        return (
            "warn",
            "deploy",
            f"unknown provider(s) in CORP_DEPLOY_PROVIDERS: {', '.join(unknown)}",
        )
    if "local" not in order:
        return ("ok", "deploy", f"order: {', '.join(order)}")
    after = order[order.index("local") + 1 :]
    reachable = [n for n in after if deploy_mod.REGISTRY[n].available()]
    if reachable:
        return (
            "warn",
            "deploy",
            f"'local' is ordered before {', '.join(reachable)} and is always available, "
            f"so it always wins and {', '.join(reachable)} will never run. "
            f"Set CORP_DEPLOY_PROVIDERS={','.join(reachable + ['local'])} to publish there.",
        )
    return ("ok", "deploy", f"order: {', '.join(order)}")


def _check_tier_coherence(s: Settings) -> tuple:
    """The trap the defaults leave: enable cloud with one free key and the normal
    tier works, but trivial still points at a local model that may be absent and
    hard at paid Anthropic. A tier aimed at a provider with no key falls through
    to local. Detect it and offer the one-click recommended routing as a fix."""
    if s.llm_mock:
        return ("ok", "routing", "mock mode: tiers are not used")
    broken = []
    for tier, model in (
        ("trivial", s.trivial_model),
        ("normal", s.normal_model),
        ("hard", s.hard_model),
    ):
        target, _ = _split(model)
        if target in ("local", "claudecode"):
            continue
        if target == "cloud":
            if not cfg.get("ANTHROPIC_API_KEY", "").strip():
                broken.append(tier)
        elif target in OPENAI_COMPAT_PROVIDERS:
            spec = OPENAI_COMPAT_PROVIDERS[target]
            configured = cfg.get(spec["key_env"], "").strip() or (
                spec.get("key_optional")
                and (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base"))
            )
            if not configured:
                broken.append(tier)
    if broken:
        return (
            "warn",
            "routing",
            f"the {', '.join(broken)} tier points at a provider with no key; it falls "
            "through to local. Use recommended routing (Providers) to fix it.",
            "recommend_routing",
        )
    return ("ok", "routing", "every tier resolves to a configured provider")


def _check_pinned_models(s: Settings, store: Store | None) -> tuple:
    """Per-role model pins, which the tier check cannot see.

    A role can be pinned to its own model — that exists so the design agent can get
    a model that reads pictures without dragging the CEO, outreach and support onto
    one ten times slower. But the pin lives in a per-company directive, and every
    check above reads the three tier settings, so a pin at a provider with no key
    made every turn of that role fall through to local while this reported that all
    was well. The lever was added and the diagnosis that exists for exactly this
    was not.

    Reads directives and keys; probes nothing.
    """
    if s.llm_mock:
        return ("ok", "pins", "mock mode: pinned models are not used")
    from . import company as company_mod
    from .orchestrator import model_overrides

    if store is None:
        return ("ok", "pins", "store unavailable, nothing to read")
    unusable, total = [], 0
    for slug in company_mod.list_slugs():
        for role, model in model_overrides(store, slug).items():
            total += 1
            target, _ = _split(model)
            if target in ("local", "claudecode"):
                continue
            if target == "cloud":
                if not cfg.get("ANTHROPIC_API_KEY", "").strip():
                    unusable.append(f"{slug}/{role} → {model}")
            elif target in OPENAI_COMPAT_PROVIDERS:
                spec = OPENAI_COMPAT_PROVIDERS[target]
                configured = cfg.get(spec["key_env"], "").strip() or (
                    spec.get("key_optional")
                    and (cfg.get(spec.get("base_env", ""), "").strip() or spec.get("base"))
                )
                if not configured:
                    unusable.append(f"{slug}/{role} → {model}")
    if unusable:
        return (
            "warn",
            "pins",
            f"pinned to a provider with no key, so every turn of that role falls "
            f"through to local: {', '.join(unusable)}. Set the key, or pin it again "
            "in the CEO chat.",
        )
    if not total:
        return ("ok", "pins", "no role is pinned; every role takes its tier")
    return ("ok", "pins", f"{total} pinned role(s), all on a configured provider")


def _check_preflight(s: Settings, store: Store | None) -> tuple:
    """What the last real preflight proved. Reads the cache; never probes.

    A probe is a real generation on a real account, and this function runs on
    every launcher start and is served over HTTP — measuring here would be the
    polled-endpoint mistake with somebody's money attached, exactly as for the
    hardware bench. `corparius preflight` is the thing that measures.

    A catalogue says a model *exists*. Only a call says this account may use it,
    which is why this outranks `_check_model_catalog` and why that one now
    stands down whenever a preflight has been run.
    """
    from . import preflight

    if s.llm_mock:
        return ("ok", "preflight", "mock mode: nothing to prove")
    if store is None:
        return ("ok", "preflight", "no store to read a previous run from")
    report = preflight.load(store)
    if not report.probes:
        return (
            "ok",
            "preflight",
            "never run. `corparius preflight` calls each configured model once, "
            "for eight tokens, and says which ones this account can really use.",
        )
    age = max(0, int((time.time() - report.ts) / 3600))
    blocked = report.blocking
    if blocked:
        return (
            "warn",
            "preflight",
            f"{', '.join(f'{p.tier} ({p.provider}:{p.model})' for p in blocked)} answered "
            f"as unusable on this account — {blocked[0].detail[:90]}. Pick another model in "
            f"Providers. Measured {age}h ago.",
            "recommend_routing",
        )
    usable = [p for p in report.probes if p.state == preflight.USABLE]
    note = f"{len(usable)}/{len(report.probes)} configured model(s) answered for real, {age}h ago"
    if report.transient:
        # Not a failure: a cold free tier looks exactly like this, and calling it
        # one would reject models that work a minute later.
        note += f"; {len(report.transient)} was rate-limited or cold at the time, not rejected"
    return ("ok", "preflight", note)


def _check_model_catalog(s: Settings) -> tuple:
    """A configured model that the provider no longer lists.

    Every `default_model` in OPENAI_COMPAT_PROVIDERS is a string frozen on the
    day it was written, and model names rot: the shipped OpenRouter default,
    `deepseek/deepseek-r1-0528:free`, stopped existing while the paid variant
    stayed, so recommended routing was writing a hard tier that 404s. Checking
    the tier against what the provider actually advertises catches that class of
    failure for all fourteen providers, now and in six months, instead of
    catching one instance of it by hand.

    Silent when it cannot know: mock mode, no key, or a provider that does not
    answer. An unreachable catalogue is not evidence that a model is gone.
    """
    if s.llm_mock:
        return ("ok", "models", "mock mode: no catalogue to check against")
    missing, checked = [], 0
    for tier, model in (
        ("trivial", s.trivial_model),
        ("normal", s.normal_model),
        ("hard", s.hard_model),
    ):
        target, name = _split(model)
        if target not in OPENAI_COMPAT_PROVIDERS or not name:
            continue
        spec = OPENAI_COMPAT_PROVIDERS[target]
        if not cfg.get(spec["key_env"], "").strip() and not spec.get("key_optional"):
            continue
        try:
            catalog = list_models(target)
        except (requests.RequestException, ValueError):
            continue
        if not catalog:
            continue
        checked += 1
        if name not in catalog:
            missing.append(f"{tier} ({target}:{name})")
    if missing:
        return (
            "warn",
            "models",
            f"{', '.join(missing)} is not in the provider's catalogue any more. Pick a live "
            "model in Providers, or use recommended routing.",
            "recommend_routing",
        )
    if not checked:
        return ("ok", "models", "no reachable provider catalogue to check against")
    return ("ok", "models", f"{checked} tier(s) name a model the provider still lists")


def run_checks(settings: Settings | None = None, store: Store | None = None) -> list[dict]:
    """Every check, in order, over exactly one store connection.

    Seven checks used to open one each and only three closed it, so every call
    leaked four connections. This function runs on every launcher start and is
    served over HTTP; on a Windows CI runner the leak pushed the console's own
    poll past its timeout, which is how it was noticed, days after shipping.

    `store` lets a caller that already holds one lend it: the console keeps a
    single connection for its whole life and has no business opening a second on
    the same file to answer a poll. A lent store is never closed here.

    The seven checks that need it take it as a required argument with no default.
    It had one, and two tests then called those checks without it and got a
    cheerful "ok, nothing to see" in place of the stale measurement and the
    from-the-future schema they had just written. Required turns that silence
    into a TypeError.
    """
    s = settings or Settings()
    lent, opened = store is not None, None
    if store is None:
        try:
            opened = store = Store(s.data_path)
        except Exception:  # noqa: BLE001 - _check_store says so, in its own words
            store = None
    try:
        checks = _all_checks(s, store)
    finally:
        if opened is not None and not lent:
            opened.close()
    out = []
    for c in checks:
        entry = {"level": c[0], "name": c[1], "message": c[2]}
        if len(c) > 3 and c[3]:  # an optional one-click fix hint for the console
            entry["fix"] = c[3]
        out.append(entry)
    return out


def _all_checks(s: Settings, store: Store | None) -> list[tuple]:
    return [
        _check_python(),
        _check_env_file(),
        _check_settings_source(s, store),
        _check_mode(s),
        _check_exposure(s),
        _check_permissions(s),
        _check_store(s, store),
        _check_secrets_at_rest(s),
        _check_companies(),
        _check_machine(s, store),
        _check_ollama(s),
        _check_providers(s),
        _check_tier_coherence(s),
        _check_pinned_models(s, store),
        _check_preflight(s, store),
        _check_model_catalog(s),
        _check_network(s),
        _check_claude_cli(s),
        _check_deploy_order(),
        _check_plugins(s),
        _check_skills(s),
        _check_apps(s),
        _check_budgets(s),
        _check_site(s),
        _check_memory(s, store),
        _check_inbox(s, store),
    ]


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
        print(
            {
                "ok": "\nAll green. Run the console: python -m corparius.cli ui",
                "warn": "\nUsable with warnings; the messages above say what to improve.",
                "fail": "\nSomething blocking needs a fix; see the FAIL lines above.",
            }[worst]
        )
    return 1 if worst == "fail" else 0

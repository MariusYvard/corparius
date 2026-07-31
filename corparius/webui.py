"""Local operator console. A stdlib HTTP server (no new dependency) serves a
single-file page (webui.html) and a small JSON API over the same Store,
Runtime and HybridRouter the CLI uses.

Scope and safety: binds to 127.0.0.1 by default. Set CORP_UI_TOKEN to require
the X-Corp-Token header on every mutating call (useful behind a reverse proxy);
the doctor fails when the console is bound off-localhost without one.

Settings saved from the page go to the store, or to .env for the bootstrap keys
that must be readable before the store opens; see corparius/cfg.py for the precedence.
Secrets are write-only: the API only ever reports whether one is set.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (
    backup,
    cfg,
    claudecli,
    deploy,
    hardware,
    i18n,
    mailbox,
    ollama_setup,
    paths,
    permissions,
    provider_check,
    settings_spec,
    sitegen,
    structured,
)
from . import company as company_mod
from . import inbox as inbox_mod
from .agents import ROSTER
from .config import Settings
from .doctor import run_checks
from .integrations import smtp_check, stripe_check, stripe_payments
from .llm import OPENAI_COMPAT_PROVIDERS, HybridRouter, _split, connected_providers
from .models import AgentRole
from .orchestrator import Runtime
from .store import Store
from .tools import TOOLS

log = logging.getLogger("corparius.webui")

# Writable home (for the .env the console writes); a shipped resource for the
# single-file console HTML. Both resolve to the repository layout from a source
# checkout and to the frozen bundle when packaged. Kept as module attributes so
# the tests can monkeypatch them.
ROOT = paths.user_home()
PAGE = paths.page_file()

# Everything the page may write: the provider panel's vars plus every row of the
# settings registry. Anything else is refused.
ALLOWED_VARS = settings_spec.WRITABLE
# Stored write-only: never returned by the API, only a "configured" boolean.
_SECRET_VARS = settings_spec.SECRETS

_CHAT_LIMIT = 30  # turns kept per company, in-process only

# The largest body the console accepts. The biggest legitimate one is a company
# YAML or a settings batch, orders of magnitude under this.
MAX_BODY = 1 << 20

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}


def _host_only(header: str) -> str:
    """The host from a Host header, without the port, bracket-aware for IPv6.

    A bare rsplit(":", 1) mangles a bracketed literal: "[::1]" splits on the
    inner colon. Peel the brackets first so "[::1]" and "[::1]:8600" both yield
    "::1", while "127.0.0.1:8600" and "localhost" are unchanged.
    """
    raw = header.strip()
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")].lower()
    return raw.rsplit(":", 1)[0].lower()


class _RequestRefused(Exception):
    """Refuse a request before any handler sees it, with the status to send.
    Raised from body parsing, where returning a value would mean having already
    read the body we are refusing to read."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _fresh_settings() -> Settings:
    """Settings are read from the environment at construction time, so a new
    instance picks up keys and toggles saved from the page."""
    return Settings()


def _companies() -> list[str]:
    return company_mod.list_slugs()


def _load_company(slug: str) -> dict | None:
    # `slug in _companies()` is the path-traversal guard: only names the glob
    # actually produced are ever opened.
    if slug not in _companies():
        return None
    try:
        return company_mod.load(company_mod.path_for(slug), slug)
    except (FileNotFoundError, ValueError):
        return None


def _merge_env_file(path: Path, values: dict[str, str]) -> None:
    """Persist KEY=value pairs, replacing existing lines and appending new
    ones. Comments and unrelated lines are left untouched.

    A newline inside a value is refused here rather than upstream, because
    upstream is three different places: the settings page, the providers panel,
    and the .env a restore reads out of an archive someone else may have built.

    It mattered. Values were written verbatim and joined with "\\n", so one
    accepted write could append lines of its own — and the line worth appending
    was `CORP_UI_ALLOWED_HOSTS`, which SECURITY.md promises cannot be set
    through the API and which a test asserts is not in ALLOWED_VARS. The name
    was not; the value was. Planting a host there turns off the DNS-rebinding
    defence, and the console stops being localhost-only.
    """
    bad = sorted(k for k, v in values.items() if "\n" in str(v) or "\r" in str(v))
    if bad:
        raise _RequestRefused(400, f"a line break is not allowed in: {', '.join(bad)}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in values:
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    lines.extend(f"{k}={v}" for k, v in values.items() if k not in seen)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class UiState:
    """Mutable server-side state shared across requests."""

    def __init__(self, settings: Settings, env_file: Path):
        self.settings = settings
        self.env_file = env_file
        self.runs: dict[str, dict] = {}
        self.chats: dict[str, deque] = {}
        self.pulls: dict = {"running": False}  # Ollama model pull, background
        # A full catalogue sweep across every configured provider. Background
        # for the same reason as a pull: it is hundreds of real calls and would
        # time out any request that waited for it.
        self.sweep: dict = {"running": False}
        self.lock = threading.Lock()
        self._store: Store | None = None

    def store(self) -> Store:
        """One connection for the process, not one per request.

        This used to return Store(...) fresh on every call, so a single
        /api/overview poll paid for a makedirs, a connect, the whole SCHEMA
        script, two chmods and a migration check - and never closed the handle.
        Worse, the resulting per-thread connections contended: twelve concurrent
        writers lost nine to `database is locked`.

        Store guards its own connection with an RLock, so sharing it is safe;
        sharing it *without* that lock is not, and was measured losing most of
        its rows silently. The double-check keeps two first requests from
        opening two connections.
        """
        if self._store is None:
            with self.lock:
                if self._store is None:
                    self._store = Store(self.settings.data_path)
        return self._store

    def close(self) -> None:
        with self.lock:
            if self._store is not None:
                self._store.close()
                self._store = None


def _overview(state: UiState, slug: str) -> dict:
    store = state.store()
    st = store.status(slug)
    flow = store.flow_metrics(slug)
    tasks = store.list_tasks(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    # Through the Store API rather than store.db: the connection is guarded by a
    # lock now, so reaching past it from here would be the unsynchronised access
    # that lock exists to prevent.
    spend = store.spend_by_agent(slug)
    actions = store.recent_actions(slug)
    frozen = store.count_actions_by_tool(slug, "circuit_breaker_freeze")
    approvals = store.list_approvals(slug, "pending")
    s = _fresh_settings()
    company_cfg = _load_company(slug) or {}
    engine = permissions.PermissionEngine.from_settings(s, company_cfg, store)
    for a in approvals:  # parameters are stored as a JSON string
        if isinstance(a.get("parameters"), str):
            try:
                a["parameters"] = json.loads(a["parameters"])
            except json.JSONDecodeError:
                pass
        tool = TOOLS.get(a.get("tool", ""))
        a["risk"] = permissions.risk_of(tool) if tool else permissions.READ
        # A tool gated by name can never be silenced by a standing rule, so the
        # console must not offer a button that would do nothing.
        a["can_remember"] = bool(tool) and engine.evaluate(tool, slug).rule != "hitl"
        # Everything the "learn more" panel needs, resolved here rather than in
        # the page: what the tool does, why this one stopped, what the agent
        # actually wrote, and what saying yes will do. An approval that shows a
        # tool name and 80 characters of JSON is a decision made blind.
        detail = a.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        detail = detail or {}
        a["detail"] = {
            "draft": detail.get("draft", ""),
            "does": detail.get("does") or (tool.description if tool else ""),
            "why": detail.get("why", ""),
            "risk_means": permissions.explain(a["risk"]),
            "on_approve": (
                f"{a.get('tool', 'the tool')} runs once, now, with exactly what you see here."
            ),
            "on_reject": "Nothing runs, and the agent moves on to the rest of its playbook.",
        }
    run = state.runs.get(slug, {})
    by_status: dict[str, list] = {
        "proposed": [],
        "approved": [],
        "in_progress": [],
        "waiting": [],
        "done": [],
    }
    for t in tasks:
        by_status.setdefault(t["status"], []).append(t)
    return {
        "ok": True,
        "company": slug,
        "tick": tick,
        "status": st,
        "flow": flow,
        "tasks": by_status,
        "approvals": approvals,
        "rules": store.list_rules(slug),
        "inbox": store.list_inbox(slug, "pending"),
        # Which console tab settles each kind of notice. Sent rather than
        # duplicated in the page: two copies of this table would drift, and the
        # failure mode is a button that silently does nothing.
        "inbox_fixes": inbox_mod.FIXES,
        "memory": store.list_memory(slug) if s.memory_enabled else [],
        "memory_enabled": s.memory_enabled,
        "permission_mode": engine.mode,
        "ask_above": engine.ask_above,
        "spend_by_agent": spend,
        # Whether any provider reported a cost at all. Without it a total of
        # 0.00 is indistinguishable from a free run, and the page would tell
        # an operator on a paid key that they spent nothing.
        "cost_reported": store.cost_reported(slug),
        "recent_actions": actions,
        "freezes": frozen,
        "session_budget": s.session_token_budget,
        "llm_mock": s.llm_mock,
        "cloud_enabled": s.cloud_enabled,
        "running": bool(run.get("running")),
        "last_run": run.get("result"),
        "loop": bool(run.get("loop")),
        "stopping": bool(run.get("running") and run.get("stop") and run["stop"].is_set()),
    }


def _providers_payload() -> dict:
    s = _fresh_settings()
    providers = []
    for name, spec in sorted(OPENAI_COMPAT_PROVIDERS.items()):
        key = cfg.get(spec["key_env"], "").strip()
        base = cfg.get(spec.get("base_env", ""), "").strip() or spec["base"]
        providers.append(
            {
                "name": name,
                "key_env": spec["key_env"],
                "base_env": spec.get("base_env"),
                "base": base,
                "key_optional": bool(spec.get("key_optional")),
                "configured": bool(key) or (bool(spec.get("key_optional")) and bool(base)),
                "key_set": bool(key),
                # Onboarding metadata: the signup page to link to, whether it
                # needs a card, the "start here" flag, and a model to route the
                # normal tier to on one-click activation. See llm.py.
                "signup": spec.get("signup", ""),
                "no_card": bool(spec.get("no_card")),
                "recommended": bool(spec.get("recommended")),
                "default_model": spec.get("default_model", ""),
            }
        )
    return {
        "ok": True,
        "providers": providers,
        "anthropic_key_set": bool(cfg.get("ANTHROPIC_API_KEY", "").strip()),
        "claude_code": s.claude_code_enabled,
        "claude_installed": claudecli.installed(),
        # Filesystem checks only, no probe: the card has to be able to say
        # "that is the chat app, not the CLI" without costing this polled
        # endpoint anything.
        "claude_desktop": claudecli.desktop_installed(),
        "claude_install_cmd": claudecli.INSTALL_CMD,
        "claude_ready": claudecli.already_on(),
        # Deliberately not the full plan. Building it needs to know whether
        # Ollama answers, and this endpoint is polled — a probe here charged
        # every operator without Ollama a connect timeout per poll, and on a
        # runner where the port is filtered rather than refused it blocked long
        # enough to fail the tests. The page derives the same "mixed vs every
        # tier" note from `providers[].configured`, which costs nothing.
        "claude_hard_tier": claudecli.HARD_TIER,
        "server_presets": settings_spec.LLM_SERVER_PRESETS,
        "cloud_enabled": s.cloud_enabled,
        "llm_mock": s.llm_mock,
        "tiers": {
            "trivial": s.trivial_model,
            "normal": s.normal_model,
            "hard": s.hard_model,
            "local_fallback": s.local_model,
            "fallback_chain": ",".join(s.llm_fallback),
        },
    }


# What the CEO chat can propose. Each maps to an existing, audited endpoint the
# operator confirms with a click, so the chat never mutates on its own and money
# or production still passes the HITL gate on the resulting run. The LLM only
# routes intent; it opens no new path.
_CEO_ACTIONS: dict[str, dict] = {
    "run_day": {
        "endpoint": "/api/run",
        "body": {"ticks": 24},
        "label_en": "Run a day",
        "label_fr": "Lancer une journée",
    },
    "run_loop": {
        "endpoint": "/api/run",
        "body": {"ticks": 24, "loop": True},
        "label_en": "Run continuously",
        "label_fr": "Lancer en continu",
    },
    "deploy": {
        "endpoint": "/api/deploy",
        "body": {},
        "label_en": "Publish the site",
        "label_fr": "Publier le site",
    },
    "build_site": {
        "endpoint": "/api/site",
        "body": {},
        "label_en": "Build the site",
        "label_fr": "Générer le site",
    },
    "backup": {
        "endpoint": "/api/backup",
        "body": {},
        "label_en": "Back up now",
        "label_fr": "Sauvegarder",
    },
    "use_claude": {
        "endpoint": "/api/claude/setup",
        "body": {},
        "no_company": True,
        "label_en": "Use my Claude subscription",
        "label_fr": "Utiliser mon abonnement Claude",
    },
}

_CEO_SCHEMA = {
    "reply": {"type": "str", "required": True, "max_len": 800},
    "intent": {"type": "str", "default": "answer", "choices": ["answer"] + list(_CEO_ACTIONS)},
    "ticks": {"type": "int", "default": 24},
}


def _chat(state: UiState, slug: str, message: str, lang: str = "en") -> dict:
    store = state.store()
    st = store.status(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    open_tasks = store.list_tasks(slug, "approved")[:5]
    spec = ROSTER[AgentRole.CEO]
    snapshot = (
        f"Company snapshot: tick {tick}, {st['actions']} actions logged, "
        f"{st['tokens']} tokens spent, {st['pending_approvals']} approvals pending, "
        f"{st['open_tasks']} open tasks. Top open tasks: "
        + ("; ".join(t["title"] for t in open_tasks) or "none")
        + "."
    )
    system = (
        f"{spec.system_prompt} You are chatting with your human operator through "
        f"the corparius console. Be concise and concrete; reference the snapshot "
        # Not "Write 'reply' in French". A model reads that as an instruction to
        # translate the word, and answers "Réponse" — reproduced live against
        # llama-3.3-70b, three questions in a row, each answered with the label
        # instead of an answer. Name the field and the language separately.
        f"when relevant. The `reply` field holds your answer to the operator, "
        f"written in {'French' if lang == 'fr' else 'English'}; do not put a label "
        f"or a heading in it, only what you want to say. "
        f"Set 'intent' to one of {', '.join(_CEO_ACTIONS)} ONLY when the operator is "
        f"clearly asking to do that thing now; otherwise 'answer'. You never execute; "
        f"the operator confirms with a button. {snapshot}"
    )
    history = state.chats.setdefault(slug, deque(maxlen=_CHAT_LIMIT))
    messages = (
        [{"role": "system", "content": system}]
        + [{"role": m["role"], "content": m["text"]} for m in history]
        + [{"role": "user", "content": message}]
    )
    # One structured call classifies intent and writes the reply. The harness
    # returns the same shape whatever model answered; in mock or on a weak model
    # it falls back to intent=answer, so the chat degrades to plain conversation.
    router = HybridRouter(_fresh_settings())
    result = structured.ask(router, messages, _CEO_SCHEMA, difficulty=spec.difficulty)
    for u in result.usages:
        store.record_usage(slug, "ceo", u.input_tokens, u.output_tokens)
    # `or message` echoed the operator's own question back at them, which reads
    # like an answer and is not one. When the model said nothing usable, say so.
    reply = (result.data.get("reply") or "").strip()
    unanswered = not reply
    if unanswered:
        reply = i18n.pick(
            lang,
            "The model did not answer. It may be rate-limited or the tier may be "
            "misconfigured — the Providers tab shows which one replied.",
            "Le modèle n'a pas répondu. Il est peut-être limité en débit, ou le palier "
            "est mal configuré — l'onglet Providers montre lequel a répondu.",
        )
    intent = result.data.get("intent", "answer")
    proposal = None
    if intent in _CEO_ACTIONS and not result.fell_back:
        spec_a = dict(_CEO_ACTIONS[intent])
        body = dict(spec_a["body"])
        if intent == "run_day":
            body["ticks"] = max(1, min(int(result.data.get("ticks", 24)), 48))
        proposal = {
            "intent": intent,
            "endpoint": spec_a["endpoint"],
            "body": body,
            "needs_company": not spec_a.get("no_company"),
            "label": i18n.pick(lang, spec_a["label_en"], spec_a["label_fr"]),
        }
    provider, _, model = result.source.partition(":")  # "mock:haiku" -> mock, haiku
    history.append({"role": "user", "text": message})
    history.append(
        {
            "role": "assistant",
            "text": reply,
            "model": model,
            "provider": provider,
            "unanswered": unanswered,
        }
    )
    return {
        "ok": True,
        "reply": reply,
        # So the page can render a failure as a failure rather than as the CEO
        # having said something odd.
        "unanswered": unanswered,
        "model": model,
        "provider": provider,
        "proposal": proposal,
        "history": list(history),
    }


def _start_run(state: UiState, slug: str, ticks: int, loop: bool = False, lang: str = "en") -> dict:
    company = _load_company(slug)
    if company is None:
        return {"ok": False, "error": f"unknown company '{slug}'"}
    stop = threading.Event()
    with state.lock:
        if state.runs.get(slug, {}).get("running"):
            return {"ok": False, "error": "a run is already in progress"}
        state.runs[slug] = {"running": True, "result": None, "stop": stop, "loop": loop}

    def _worker() -> None:
        try:
            runtime = Runtime(_fresh_settings(), state.store())
            result = runtime.run(company, ticks=ticks, loop=loop, should_stop=stop.is_set)
            state.runs[slug] = {"running": False, "result": result}
        except Exception:  # surface, never swallow; detail to the log, not the operator
            log.exception("run failed for %s", slug)
            state.runs[slug] = {
                "running": False,
                "result": {
                    "error": i18n.pick(
                        lang,
                        "The run stopped on an unexpected error. See the server log for details.",
                        "Le run s'est arrêté sur une erreur inattendue. Voir le journal du serveur.",
                    )
                },
            }

    threading.Thread(target=_worker, daemon=True, name=f"corparius-run-{slug}").start()
    return {"ok": True, "running": True, "loop": loop}


def _stop_run(state: UiState, slug: str) -> dict:
    """Ask the loop to stop. It lands within a tick; the thread is never killed,
    so the company's clock and the action log stay consistent."""
    with state.lock:
        run = state.runs.get(slug) or {}
        if not run.get("running"):
            return {"ok": False, "error": "no run in progress"}
        stop = run.get("stop")
    if stop is None:
        return {"ok": False, "error": "this run cannot be stopped"}
    stop.set()
    return {"ok": True, "stopping": True}


_DEFAULT_AGENTS = company_mod.DEFAULT_AGENTS  # kept: the wizard's checkbox list


def _create_company(state: UiState, body: dict) -> dict:
    """The wizard. It asks for two fields and fills the rest from the same
    validator the editor uses, so a company created here and one edited later
    can never disagree about what a company is."""
    # A template prefills offer/icp/agents; explicit body fields still win, so the
    # operator's typed name and product override the template's examples.
    tpl = company_mod.template(str(body.get("template", ""))) or {}
    lang = "fr" if str(body.get("lang", "")).startswith("fr") else "en"
    offer = {"product": body.get("product") or tpl.get(f"product_{lang}", "")}
    if tpl:
        offer["price_eur"] = tpl.get("price_eur")
        offer["billing"] = tpl.get("billing", "stripe")
    icp = {"segment": body.get("segment") or tpl.get(f"segment_{lang}", "")}
    if tpl:
        icp["channels"] = tpl.get("channels", [])
        icp["pains"] = tpl.get(f"pains_{lang}", [])
    agents = {**tpl.get("agents", {}), **dict(body.get("agents", {}))}
    cfg, errors, warnings = company_mod.validate(
        {
            "name": body.get("name", ""),
            "one_liner": body.get("one_liner", ""),
            "offer": offer,
            "icp": icp,
            "agents": agents,
            "budgets": {"session_tokens": body.get("session_tokens", 80000)},
        }
    )
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    path = company_mod.path_for(cfg["slug"])
    if path.exists():
        return {"ok": False, "error": f"company '{cfg['slug']}' already exists"}
    company_mod.dump(cfg, path)
    state.store().save_state(cfg["slug"], {"tick": 0})
    log.info("company created from the console: %s", cfg["slug"])
    return {"ok": True, "slug": cfg["slug"], "companies": _companies(), "warnings": warnings}


def _company_payload(slug: str) -> dict:
    cfg = _load_company(slug)
    if cfg is None:
        return {"ok": False, "error": f"unknown company '{slug}'"}
    # A broken file opens in the editor with its problems named, rather than
    # returning a 404 that strands the operator with nothing to fix it from.
    _cfg, errors, warnings = company_mod.validate(cfg)
    return {
        "ok": True,
        "company": cfg,
        "path": str(company_mod.path_for(slug)),
        "warnings": warnings,
        "problems": errors,
        "roles": list(company_mod.ROLES),
        "channels": list(company_mod.CHANNELS),
        "billing": list(company_mod.BILLING),
        "tools": sorted(TOOLS),
    }


def _save_company(state: UiState, slug: str, body: dict) -> dict:
    if slug not in _companies():
        return {"ok": False, "error": f"unknown company '{slug}'"}
    incoming = dict(body or {})
    incoming["slug"] = slug  # the slug is the directory; renaming is a move, not an edit
    cfg, errors, warnings = company_mod.validate(incoming)
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    company_mod.dump(cfg, company_mod.path_for(slug))
    log.info("company edited from the console: %s", slug)
    return {**_company_payload(slug), "warnings": warnings, "saved": True}


def _delete_company(state: UiState, slug: str, confirm: str, purge: bool) -> dict:
    if slug not in _companies():
        return {"ok": False, "error": f"unknown company '{slug}'"}
    if confirm != slug:
        return {"ok": False, "error": "type the company slug to confirm"}
    try:
        dest = company_mod.trash(slug)
    except FileNotFoundError:
        return {"ok": False, "error": f"unknown company '{slug}'"}
    if purge:
        state.store().purge_company(slug)
    log.info("company moved to trash from the console: %s -> %s", slug, dest)
    return {"ok": True, "companies": _companies(), "trashed": str(dest), "purged": bool(purge)}


def _persist(state: UiState, values: dict[str, str], unset: list[str] | None = None) -> dict:
    """Write settings saved from the page, each to the layer it belongs to.

    Bootstrap keys (cfg.BOOTSTRAP) go to .env: they must be readable before the
    store can be opened, so they cannot live in it. Everything else goes to the
    settings table, which outranks .env and survives a restart.

    Nothing is written to os.environ. That layer belongs to whoever started the
    process; writing it here would promote a console value above every later
    edit and make cfg.source() report "env" for a value the console itself set.
    A key the process environment already defines is reported back as shadowed
    rather than silently ignored.

    Returns the meta the caller merges into its payload.
    """
    unset = unset or []
    boot = {k: v for k, v in values.items() if k in cfg.BOOTSTRAP}
    stored = {k: v for k, v in values.items() if k not in cfg.BOOTSTRAP}
    if boot:
        _merge_env_file(state.env_file, boot)
    if stored or unset:
        store = state.store()
        for key, value in stored.items():
            store.set_setting(key, value, secret=key in _SECRET_VARS)
        for key in unset:
            store.delete_setting(key)
        if any(k in cfg.BOOTSTRAP for k in unset):
            _merge_env_file(state.env_file, {k: "" for k in unset if k in cfg.BOOTSTRAP})
    cfg.invalidate()
    meta: dict = {}
    # Setting or clearing the passphrase from the page has to rewrite what is
    # already stored, exactly as `corparius secrets on` does. Without this the
    # field looked like it encrypted the operator's keys and only affected the
    # next write — the trap that made the setting mean less than it said.
    if "CORP_SECRET_KEY" in values or "CORP_SECRET_KEY" in unset:
        from . import secretbox

        try:
            changed = state.store().rewrite_secrets(to_encrypted=secretbox.enabled())
        except Exception:  # noqa: BLE001 - a wrong passphrase must not 500 the page
            meta["secrets_error"] = (
                "The stored secrets could not be rewritten with that passphrase. "
                "It has to be the one they were encrypted with."
            )
        else:
            meta["secrets_rewritten"] = sorted(changed)
    shadowed = [k for k in list(values) + unset if os.environ.get(k) is not None]
    if shadowed:
        meta["shadowed"] = sorted(shadowed)
    restart = sorted(k for k in list(values) + unset if k in cfg.BOOTSTRAP)
    if restart:
        meta["restart_required"] = restart
    return meta


def _set_env(state: UiState, values: dict) -> dict:
    """The providers panel: toggles, routing tiers and provider keys."""
    clean: dict[str, str] = {}
    for key, value in values.items():
        if key not in ALLOWED_VARS:
            return {"ok": False, "error": f"variable '{key}' is not settable"}
        clean[key] = str(value).strip()
    meta = _persist(state, clean)
    return {**_providers_payload(), **meta}


def _edit_task(store, body: dict) -> tuple[int, dict]:
    """Edit fields, decide, or both. The CLI could already retitle and
    reprioritise a task; the console could only approve or reject one."""
    try:
        task_id = int(body.get("id"))  # type: ignore[arg-type]  # None -> TypeError, caught here
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "a task id is required"}
    decision = body.get("decision")
    if decision is not None and decision not in ("approved", "rejected"):
        return 400, {"ok": False, "error": "decision must be approved or rejected"}

    fields: dict = {}
    if "title" in body:
        title = str(body["title"]).strip()
        if not title:
            return 400, {"ok": False, "error": "title cannot be empty"}
        fields["title"] = title
    if "priority" in body:
        try:
            fields["priority"] = max(0, min(int(body["priority"]), 5))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "priority must be a whole number"}
    if "target" in body:
        target = str(body["target"]).strip()
        if target not in {r.value for r in AgentRole}:
            return 400, {"ok": False, "error": f"unknown agent '{target}'"}
        fields["target"] = target
    if "tool" in body:
        tool = str(body["tool"]).strip()
        if tool and tool not in TOOLS:
            return 400, {"ok": False, "error": f"unknown tool '{tool}'"}
        fields["tool"] = tool
    if not fields and decision is None:
        return 400, {"ok": False, "error": "nothing to change"}
    if fields:
        store.update_task(task_id, **fields)
    if decision:
        store.set_task_status(task_id, decision, str(body.get("note", "via console")))
    return 200, {"ok": True, "id": task_id, "changed": sorted(fields)}


def _deploy(state: UiState, slug: str) -> tuple[int, dict]:
    company = _load_company(slug)
    if company is None:
        return 404, {"ok": False, "error": f"unknown company '{slug}'"}
    data_path = _fresh_settings().data_path
    out_dir = paths.site_dir(data_path, slug)
    if not paths.site_index(data_path, slug).exists():
        sitegen.build_site(company, str(out_dir), store=state.store())
    res = deploy.deploy_result(str(out_dir))
    if res["ok"]:
        # Remember where it went, so the "go live" card can show the live URL
        # again after a reload, not only in this response.
        try:
            (out_dir / ".published").write_text(str(res["result"]), encoding="utf-8")
        except OSError:
            pass
    # The envelope succeeded; whether anything published is the payload's news.
    return 200, {
        "ok": True,
        "published": res["ok"],
        "provider": res["provider"],
        "result": res["result"],
        "errors": res["errors"],
        "skipped": res["skipped"],
    }


def _golive_status(slug: str) -> dict:
    """The three things between a mock company and one that can take money: a
    checkout link, a mail account, and a public host. Reported as booleans plus
    the live URL, so one card can guide the operator from A to Z."""
    company = _load_company(slug) or {}
    offer = company.get("offer", {}) or {}
    pay = (
        str(offer.get("payment_link") or "").strip()
        or cfg.get("CORP_STRIPE_PAYMENT_LINK", "").strip()
    )
    published_url = ""
    marker = paths.site_dir(_fresh_settings().data_path, slug) / ".published"
    if marker.is_file():
        target = marker.read_text(encoding="utf-8").strip()
        if target.startswith("netlify:") and "http" in target:
            published_url = target.split("netlify:", 1)[1]
    smtp_ok = bool(cfg.get("CORP_SMTP_HOST", "").strip() and cfg.get("CORP_SMTP_USER", "").strip())
    return {
        "ok": True,
        "payment": {"wired": pay.startswith("http"), "link": pay},
        "mail": {"wired": smtp_ok},
        "hosting": {
            "token_set": bool(cfg.get("NETLIFY_AUTH_TOKEN", "").strip()),
            "published_url": published_url,
        },
    }


def _ollama_pull(state: UiState, models: list) -> dict:
    """Pull the named models (or every missing one) in the background. A pull is
    gigabytes, so it runs in a thread and reports progress through /api/ollama,
    the same shape as a run."""
    models = [str(m).strip() for m in models if str(m).strip()] or ollama_setup.status()["missing"]
    if not models:
        return {"ok": True, "detail": "nothing to pull"}
    with state.lock:
        if state.pulls.get("running"):
            return {"ok": False, "error": "a pull is already in progress"}
        state.pulls = {"running": True, "progress": "", "done": [], "failed": []}

    def _worker() -> None:
        for model in models:

            def note(line):
                state.pulls["progress"] = line

            res = ollama_setup.pull(model, on_line=note)
            (state.pulls["done"] if res["ok"] else state.pulls["failed"]).append(model)
        state.pulls["running"] = False
        state.pulls["progress"] = "done"

    threading.Thread(target=_worker, daemon=True, name="corparius-ollama-pull").start()
    return {"ok": True, "pulling": models}


def _claude_setup(state: UiState, all_tiers: bool = False) -> dict:
    """One press: prove the CLI works, then flip mock off, cloud on, Claude Code
    on, and point the tiers at claudecode. The four scattered settings and the
    hand-edited tier strings were most of the friction.

    Free providers, when connected, keep the trivial and normal tiers: a
    subscription is metered in usage windows, and a social post every two hours
    is not what those windows are for."""
    result = claudecli.check()
    if not result["ok"]:
        # Do not switch a company to a provider that will not answer.
        return {"ok": False, "error": result["detail"], "check": result}
    # One probe, reused. _providers_payload() below used to run a second one,
    # and two four-second connect timeouts on a machine with no Ollama exceeded
    # the console client's own timeout.
    local_trivial, _why = hardware.recommended_local(state.store(), _fresh_settings())
    from . import modelinfo, preflight

    applied = claudecli.plan(
        connected_providers(),
        local_trivial,
        all_tiers=all_tiers,
        proven=preflight.proven_map(state.store()),
        catalogue=modelinfo.cached(state.store()),
        scores=modelinfo.operator_scores(),
    )
    _persist(state, applied)
    payload = _providers_payload()
    return {**payload, "check": result, "applied": applied}


def _oops(lang: str = "en") -> str:
    """The message for an unexpected error. The full traceback goes to the server
    log; the operator gets a sentence, not Python internals."""
    return i18n.pick(
        lang,
        "Something went wrong on the console. The details are in the server log.",
        "Un problème est survenu dans la console. Les détails sont dans le journal du serveur.",
    )


def _mail_check(to: str = "", lang: str = "en") -> dict:
    """Prove the mail account in one press: send, then read. Reported as two
    lines because they fail for different reasons and an operator needs to know
    which half is broken."""
    send = smtp_check(to, lang=lang)
    read = mailbox.check(lang=lang)
    sending = i18n.pick(lang, "Sending", "Envoi")
    reading = i18n.pick(lang, "Reading", "Lecture")
    lines = [f"{sending}: {send['detail']}", f"{reading}: {read['detail']}"]
    if not send["configured"] and not read["configured"]:
        return {
            "ok": False,
            "detail": i18n.pick(
                lang,
                "No mail account set yet. Pick a provider above, give the address "
                "and an app password.",
                "Aucun compte mail réglé. Choisissez un fournisseur ci-dessus, donnez "
                "l'adresse et un mot de passe d'application.",
            ),
        }
    return {
        "ok": bool(send["ok"] and read["ok"]),
        "send_ok": send["ok"],
        "read_ok": read["ok"],
        "detail": "\n".join(lines),
    }


def _settings_payload() -> dict:
    return {
        "ok": True,
        "groups": settings_spec.GROUPS,
        "fields": [settings_spec.describe(f.key) for f in settings_spec.SPEC],
        "warning": {"en": settings_spec.WARN_EN, "fr": settings_spec.WARN_FR},
        "mail_presets": settings_spec.MAIL_PRESETS,
        "mail_steps": _mail_steps(),
    }


def _mail_steps() -> dict:
    """The per-provider steps, each carrying whether it is actually done.

    Resolved here rather than in the page because "done" is a fact about this
    installation's settings, not about the browser — the same reason the
    approval panel resolves what a tool does server-side.

    A step with no `needs` is one corparius cannot check: installing Proton
    Bridge, reading a password off somebody else's dashboard. Those report
    `checkable: false` and the console shows them as something to do rather
    than as something outstanding, because a step that can never turn green is
    worse than no state at all.
    """
    out: dict[str, list[dict]] = {}
    for provider, steps in settings_spec.MAIL_STEPS.items():
        resolved = []
        for step in steps:
            needs = step.get("needs") or []
            resolved.append(
                {
                    "en": step["en"],
                    "fr": step["fr"],
                    "url": step.get("url", ""),
                    "checkable": bool(needs),
                    "done": bool(needs) and all(cfg.get(key, "").strip() for key in needs),
                }
            )
        out[provider] = resolved
    return out


def _set_settings(state: UiState, values: dict, unset: list) -> dict:
    """Validate against the registry, then persist. An empty value clears the
    setting rather than storing an empty string, so the layer below shows
    through again."""
    clean: dict[str, str] = {}
    drop: list[str] = [k for k in unset if k in settings_spec.BY_KEY]
    errors: list[str] = []
    for key, raw in values.items():
        spec = settings_spec.BY_KEY.get(key)
        if spec is None:
            return {"ok": False, "error": f"unknown setting '{key}'"}
        value, err = settings_spec.coerce(spec, raw)
        if err:
            errors.append(err)
        elif value is None:
            drop.append(key)
        else:
            clean[key] = value
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    meta = _persist(state, clean, drop)
    return {**_settings_payload(), **meta}


def _theme_file() -> Path:
    """Where the console's colour choice lives: a small JSON in the data dir,
    deliberately separate from the settings table (this is per-instance UI state,
    not app configuration). Persisting it here is what makes the theme follow the
    operator across browsers and devices on the same instance."""
    return Path(_fresh_settings().data_path) / "ui_theme.json"


def _theme_get() -> dict:
    try:
        data = json.loads(_theme_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _theme_set(body: dict) -> dict:
    """Merge validated fields (mode, hue, chroma) into the stored theme. A null or
    empty value clears a field (back to the code default)."""
    current = _theme_get()
    if "mode" in body:
        mode = body["mode"]
        if mode in ("dark", "light"):
            current["mode"] = mode
        elif mode in (None, ""):
            current.pop("mode", None)
    for key, lo, hi in (("hue", 0.0, 360.0), ("chroma", 0.0, 2.0)):
        if key not in body:
            continue
        value = body[key]
        if value in (None, ""):
            current.pop(key, None)
            continue
        try:
            if lo <= float(value) <= hi:
                current[key] = str(value)[:16]
        except (TypeError, ValueError):
            pass
    try:
        path = _theme_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current), encoding="utf-8")
    except OSError:
        pass
    return current


def _plugins_action(body: dict) -> dict:
    """Enable/disable/remove an installed plugin, or install a VERIFIED one from
    the curated registry. Installing an unverified plugin is deliberately not
    reachable from the console — that path is CLI-only, behind the opt-in."""
    from . import plugins

    action = str(body.get("action", ""))
    name = str(body.get("name", "")).strip()
    try:
        if action == "enable":
            plugins.set_enabled(name, True)
        elif action == "disable":
            plugins.set_enabled(name, False)
        elif action == "remove":
            plugins.remove(name)
        elif action == "install":
            plugins.install_from_registry(name)  # verified only from the console
        else:
            return {"ok": False, "error": f"unknown action '{action}'"}
    except plugins.PluginError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "restart_required": True, **plugins.status()}


@dataclass
class Ctx:
    """One request, normalised. GET reads its parameters from the query string
    and POST from the JSON body; handlers should not care which."""

    state: UiState
    path: str
    query: dict
    body: dict
    slug: str
    lang: str

    def store(self) -> Store:
        return self.state.store()


# --- route handlers -------------------------------------------------------
# Each returns (status, payload) or (status, payload, content_type). Pulling
# them out of the if/elif chains makes them callable without an HTTP round trip.


def _route_page(ctx):
    return 200, PAGE.read_bytes(), "text/html"


def _route_companies_get(ctx):
    return 200, {"ok": True, "companies": _companies(), "templates": company_mod.TEMPLATES}


def _route_overview(ctx):
    return 200, _overview(ctx.state, ctx.slug)


def _route_providers_get(ctx):
    return 200, _providers_payload()


def _route_settings_get(ctx):
    return 200, _settings_payload()


def _route_company_get(ctx):
    result = _company_payload(ctx.slug)
    return (200 if result["ok"] else 404), result


def _route_session(ctx):
    # Tells the page whether it must send X-Corp-Token. It never serves the
    # token itself.
    return 200, {"ok": True, "token_required": bool(cfg.get("CORP_UI_TOKEN", "").strip())}


def _route_ollama_get(ctx):
    result = ollama_setup.status(lang=ctx.lang)
    pulls = ctx.state.pulls
    if pulls.get("running"):
        result = {**result, "detail": pulls.get("progress") or "pulling...", "pulling": True}
    # The cached measurement only — this endpoint is polled while a pull runs.
    settings = _fresh_settings()
    prof = hardware.profile(ctx.store(), max_age_days=settings.bench_max_age_days)
    choice, why = hardware.recommended_local(ctx.store(), settings, result.get("installed"))
    return 200, {
        "ok": True,
        "result": {**result, "machine": prof, "local_model": choice, "local_reason": why},
    }


def _route_ollama_bench(ctx):
    """Measure, on a button press. The one place in the console that may: it
    costs a real generation — 93 seconds to load the configured model on the
    machine this was written for — so it can never sit on a polled path."""
    settings = _fresh_settings()
    models = hardware.installed_models()
    if not models:
        return 200, {"ok": True, "result": {"ok": False, "detail": "no local model to measure"}}
    want = hardware.best_local_model(models, prefer=_split(settings.trivial_model)[1])
    spec = hardware.specs()
    measured = hardware.measure(want or models[0]["name"])
    if measured["ok"]:
        hardware.profile_save(ctx.store(), spec, measured)
    return 200, {"ok": True, "result": measured}


def _route_drafts_get(ctx):
    """What the agents wrote and nothing has published.

    They were being written and thrown away — the social agent was the largest
    line in one company's spend and left nothing behind. Keeping them was half
    the fix; this is the half that lets someone read them.
    """
    store = ctx.store()
    return 200, {
        "ok": True,
        "drafts": store.list_drafts(ctx.slug, limit=100),
        # What actually gates the agent: `draft` and `queued` together.
        "queued": store.count_unpublished(ctx.slug),
        "published": store.count_drafts(ctx.slug, "published"),
        "cap": cfg.get_int("CORP_SOCIAL_QUEUE_MAX", 5),
    }


def _route_drafts_post(ctx):
    """Mark one published or discarded.

    `published` is the operator's word for "this went out", not a claim that
    corparius sent it — nothing here publishes to a social channel. It stops the
    post counting against the queue, which is what lets the agent resume.
    """
    try:
        draft_id = int(ctx.body.get("id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "a draft id is required"}
    state = str(ctx.body.get("state", "")).strip()
    if state not in ("published", "discarded", "queued"):
        return 400, {"ok": False, "error": "state must be published, discarded or queued"}
    store = ctx.store()
    if not store.set_draft_state(draft_id, state):
        return 404, {"ok": False, "error": "no such draft"}
    return 200, {
        "ok": True,
        "drafts": store.list_drafts(ctx.slug, limit=100),
        # What actually gates the agent: `draft` and `queued` together.
        "queued": store.count_unpublished(ctx.slug),
        "published": store.count_drafts(ctx.slug, "published"),
        "cap": cfg.get_int("CORP_SOCIAL_QUEUE_MAX", 5),
    }


def _route_site_get(ctx):
    site = paths.site_index(_fresh_settings().data_path, ctx.slug)
    return 200, {
        "ok": True,
        "built": site.is_file(),
        "mtime": site.stat().st_mtime if site.is_file() else None,
    }


def _route_site_serve(ctx):
    parts = ctx.path.split("/")
    slug = parts[2] if len(parts) > 2 else ""
    site = paths.site_index(_fresh_settings().data_path, slug)
    # `slug in _companies()` is the path-traversal guard, as everywhere else.
    if slug in _companies() and site.is_file():
        return 200, site.read_bytes(), "text/html"
    return 404, {"ok": False, "error": "site not built yet"}


def _route_payments_get(ctx):
    return 200, {"ok": True, **stripe_payments()}


def _route_doctor(ctx):
    return 200, {"ok": True, "checks": run_checks(_fresh_settings())}


def _route_update(ctx):
    # Off unless CORP_UPDATE_CHECK is on; when off this makes no network call.
    # See corparius/update_check.py.
    from . import selfupdate, update_check

    return 200, {"ok": True, **update_check.check(), "can_apply": not selfupdate.why_not()}


def _route_update_apply(ctx):
    """Download the newest release and swap the binary, on a button press.

    A POST, never the polled GET beside it: this one downloads tens of
    megabytes and then replaces the program. The route exists on every build so
    the refusal is explainable — from source or Docker it says what to do
    instead rather than pretending the button is missing.
    """
    from . import selfupdate, update_check

    info = update_check.check()
    if not info.get("update_available"):
        return 200, {"ok": False, "error": "already up to date"}
    # The tag comes from the version check, never from the request. It used to
    # be read out of the body, and `..` in it walked the download URL out of
    # this repository entirely — requests normalises dot segments, so
    # `../../../../someone/else/releases/download/v1` resolved to their repo.
    # The checksum was no defence: SHA256SUMS was fetched from the same
    # attacker-chosen directory, so verification agreed with itself and the
    # binary was installed and then run. The CLI never had this; it asks
    # update_check. So does this now.
    tag = f"v{info.get('latest', '')}"
    try:
        return 200, {"ok": True, "result": selfupdate.apply(tag)}
    except selfupdate.UpdateError as exc:
        return 200, {"ok": False, "error": str(exc)}


def _route_plugins_get(ctx):
    from . import plugins, skills

    s = _fresh_settings()
    # Near enough to read-only. A skill is a file the operator wrote and the
    # console will not become a second, worse text editor — but one edit earns
    # its place: writing `allowed-tools` into a skill that has none. Unscoped, it
    # rides on every prompt of every agent (3 815 characters, measured, on the
    # owner's own company), and until now the console could only say so.
    catalog: list[dict] = []
    if s.skills_enabled:
        loader = skills.SkillLoader.for_company(ctx.slug or "", max_chars=s.skill_max_chars)
        catalog = [
            {
                "name": sk.name,
                "description": sk.description,
                "scope": sk.scope,
                "tools": sk.allowed_tools,
                "unknown_tools": [t for t in sk.allowed_tools if t not in TOOLS],
                "chars": len(sk.instructions),
                "unscoped": sk.unscoped,
                "truncated": len(sk.instructions) > s.skill_max_chars,
                "path": str(sk.path),
            }
            for sk in loader.skills
        ]
    return 200, {
        "ok": True,
        **plugins.status(),
        "skills": catalog,
        "skills_enabled": s.skills_enabled,
        "skills_always_on_chars": loader.always_on_chars() if s.skills_enabled else 0,
        # So the scoping picker offers real names instead of asking the operator
        # to know them. Sorted, because it is a list a human reads.
        "tool_names": sorted(TOOLS),
    }


def _route_skill_scope(ctx):
    """Name the tools an unscoped skill applies to.

    The one write the skills panel does. Refuses a tool that does not exist,
    because a skill scoped to a name nobody has never applies — silently, which
    is a worse outcome than the tax it was meant to fix.
    """
    from . import skills

    s = _fresh_settings()
    if not s.skills_enabled:
        return 400, {"ok": False, "error": "skills are off"}
    name = str(ctx.body.get("name", "")).strip()
    tools = [str(t).strip() for t in (ctx.body.get("tools") or []) if str(t).strip()]
    loader = skills.SkillLoader.for_company(ctx.slug or "", max_chars=s.skill_max_chars)
    skill = next((sk for sk in loader.skills if sk.name == name), None)
    if skill is None:
        return 404, {"ok": False, "error": f"no skill named {name!r}"}
    error = skills.scope_to(skill.path, tools)
    if error:
        return 400, {"ok": False, "error": error}
    log.info("skill %s scoped to %s", name, ", ".join(tools))
    return 200, {"ok": True, "name": name, "tools": tools}


def _route_theme_get(ctx):
    return 200, {"ok": True, **_theme_get()}


def _route_chat_get(ctx):
    return 200, {"ok": True, "history": list(ctx.state.chats.get(ctx.slug, []))}


def _route_companies_post(ctx):
    return 200, _create_company(ctx.state, ctx.body)


def _route_approvals_post(ctx):
    decision = ctx.body.get("decision")
    if decision not in ("approved", "rejected"):
        return 400, {"ok": False, "error": "decision must be approved or rejected"}
    store = ctx.store()
    approval_id = str(ctx.body.get("id"))
    # Read before writing: the approval carries the company, and this endpoint
    # is deliberately not slug-scoped so an approval can be decided from
    # anywhere it is visible.
    approval = store.get_approval(approval_id)
    done = store.set_approval_status(
        approval_id, decision, str(ctx.body.get("note", "via console"))
    )
    # "Approve, and stop asking" is granted here rather than through its own
    # endpoint, because it is one operator gesture and must not half-apply.
    remembered = ""
    scope = str(ctx.body.get("remember", "")).strip()
    if done and decision == "approved" and scope in ("run", "always") and approval:
        slug = approval["company"]
        tool = TOOLS.get(approval["tool"])
        engine = permissions.PermissionEngine.from_settings(
            _fresh_settings(), _load_company(slug) or {}, store
        )
        if tool and engine.evaluate(tool, slug).rule != "hitl":
            store.add_rule(slug, approval["tool"], scope, "granted from the console")
            remembered = scope
    return (200 if done else 404), {
        "ok": done,
        "remembered": remembered,
        "error": None if done else "approval not found",
    }


def _route_inbox_post(ctx):
    """Answer a question, or dismiss a notice. First responder wins: a second
    answer to a decided item is refused rather than overwriting one the waiting
    work has already moved on."""
    item = str(ctx.body.get("id", "")).strip()
    if not item:
        return 400, {"ok": False, "error": "id is required"}
    store = ctx.store()
    done = store.resolve_inbox(item, str(ctx.body.get("answer", "")))
    freed = store.release_waiting_tasks(ctx.slug) if done and ctx.slug else {"released": 0}
    return (200 if done else 409), {
        "ok": done,
        "released": freed["released"],
        "error": None if done else "already answered, or no such item",
    }


def _route_memory_post(ctx):
    """Pin or forget one fact. The operator owns their company's memory the same
    way they own its secrets: a wrong thing an agent wrote down must be
    removable without opening the database."""
    try:
        memory_id = int(ctx.body.get("id", 0))
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "id must be a number"}
    action = str(ctx.body.get("action", "")).strip()
    if action == "forget":
        done = ctx.store().forget(memory_id)
    elif action in ("pin", "unpin"):
        done = ctx.store().pin_memory(memory_id, action == "pin")
    else:
        return 400, {"ok": False, "error": "action must be pin, unpin or forget"}
    return (200 if done else 404), {"ok": done, "error": None if done else "no such memory"}


def _route_rules_post(ctx):
    """Revoke a standing rule. Granting one goes through the approval it came
    from; revoking has to stand alone, or a rule granted by mistake could only
    be undone by editing the database."""
    tool = str(ctx.body.get("tool", "")).strip()
    if not tool:
        return 400, {"ok": False, "error": "tool is required"}
    dropped = ctx.store().drop_rule(ctx.slug, tool)
    return (200 if dropped else 404), {
        "ok": dropped,
        "error": None if dropped else "no standing rule for that tool",
    }


def _route_tasks_post(ctx):
    return _edit_task(ctx.store(), ctx.body)


def _route_site_post(ctx):
    company = _load_company(ctx.slug)
    if company is None:
        return 404, {"ok": False, "error": f"unknown company '{ctx.slug}'"}
    out_dir = paths.site_dir(_fresh_settings().data_path, ctx.slug)
    headline = str(ctx.body.get("headline", "")).strip()
    sitegen.build_site(company, str(out_dir), headline=headline or None, store=ctx.state.store())
    return 200, {"ok": True, "built": True}


def _route_deploy_post(ctx):
    return _deploy(ctx.state, ctx.slug)


def _route_backup_post(ctx):
    path = backup.make_backup(_fresh_settings().data_path)
    return 200, {
        "ok": True,
        "name": path.name,
        "size": path.stat().st_size,
        "warning": {"en": backup.WARNING_EN, "fr": backup.WARNING_FR},
    }


def _route_run_stop(ctx):
    return 200, _stop_run(ctx.state, ctx.slug)


def _route_run_post(ctx):
    ticks = max(1, min(int(ctx.body.get("ticks", 6)), 48))
    return 200, _start_run(
        ctx.state, ctx.slug, ticks, loop=bool(ctx.body.get("loop")), lang=ctx.lang
    )


def _route_providers_post(ctx):
    return 200, _set_env(ctx.state, dict(ctx.body.get("values", {})))


def _route_golive(ctx):
    return 200, _golive_status(ctx.slug)


def _route_tiers_recommend(ctx):
    # One click to a coherent routing over the free providers actually connected:
    # flip mock off and cloud on, then fill every tier so none is left pointing at
    # an unconfigured provider (the trap the defaults leave after a single key).
    from .llm import recommended_routing

    local_trivial, _why = hardware.recommended_local(ctx.store(), _fresh_settings())
    # What a preflight actually proved, so "recommended" never writes a tier
    # this key cannot call. Empty until someone runs one, and then this behaves
    # exactly as it did before.
    from . import modelinfo, preflight

    routing = recommended_routing(
        connected_providers(),
        local_trivial,
        hard=claudecli.HARD_TIER if claudecli.already_on() else "",
        fallback_tail=claudecli.FALLBACK_LADDER if claudecli.already_on() else (),
        proven=preflight.proven_map(ctx.store()),
        catalogue=modelinfo.cached(ctx.store()),
        scores=modelinfo.operator_scores(),
    )
    if routing is None:
        return 400, {
            "ok": False,
            "error": "connect a free provider first (Groq or Cerebras are the quickest)",
        }
    result = _set_env(
        ctx.state, {"CORP_LLM_MOCK": "false", "CORP_CLOUD_ENABLED": "true", **routing}
    )
    return (200 if result.get("ok") else 400), {**result, "routing": routing}


def _route_provider_models(ctx):
    # The models a provider advertises, so a tier can be filled from a list rather
    # than a remembered string. A network failure is reported, never a 500.
    from . import preflight
    from .llm import list_models

    name = str(ctx.body.get("name", ""))
    if name not in OPENAI_COMPAT_PROVIDERS:
        return 404, {"ok": False, "error": f"unknown provider '{name}'"}
    # What a previous preflight actually proved, alongside the advertised list.
    # Measured on NVIDIA with a real key: 10 of 18 catalogue entries answered
    # 404. Offering the catalogue alone is offering a coin flip; offering it
    # with the proven ones marked is offering what is known.
    proved = {r["model"]: r["state"] for r in ctx.state.store().known_probes(name)}
    try:
        models = list_models(name)
    except Exception as exc:  # network/HTTP/parse: report, do not crash the handler
        log.info("model list for %s failed: %s", name, exc)
        return 200, {
            "ok": False,
            "models": sorted(proved),
            "proved": proved,
            "error": "could not list models; showing what a preflight proved",
        }
    # A model that answered but is no longer advertised is still callable, and
    # dropping it would hide the one fact here that was measured rather than
    # claimed.
    every = sorted(set(models) | {m for m, s in proved.items() if s == preflight.USABLE})
    return 200, {"ok": True, "models": every, "proved": proved}


def _route_settings_post(ctx):
    result = _set_settings(
        ctx.state, dict(ctx.body.get("values", {})), list(ctx.body.get("unset", []))
    )
    return (200 if result.get("ok") else 400), result


def _route_plugins_post(ctx):
    result = _plugins_action(ctx.body)
    return (200 if result.get("ok") else 400), result


def _route_theme_post(ctx):
    return 200, {"ok": True, **_theme_set(ctx.body)}


def _route_test_mail(ctx):
    # One button, both directions. A real send and a real read: setting a mail
    # account and hoping is the friction, and this is the answer to "did it work?".
    return 200, {"ok": True, "result": _mail_check(str(ctx.body.get("to", "")), ctx.lang)}


def _route_test_payments(ctx):
    return 200, {"ok": True, "result": stripe_check(lang=ctx.lang)}


def _route_test_claude(ctx):
    return 200, {"ok": True, "result": claudecli.check(lang=ctx.lang)}


def _route_claude_install(ctx):
    """Install the CLI, on a button press.

    It puts a global npm package on the operator's machine, so it never happens
    as a side effect of a status check — only here, and only from this console,
    which is bound to localhost behind a token.
    """
    if claudecli.installed():
        return 200, {"ok": True, "result": {"ok": True, "detail": "already installed"}}
    return 200, {"ok": True, "result": claudecli.install()}


def _route_claude_setup(ctx):
    result = _claude_setup(ctx.state, all_tiers=bool(ctx.body.get("all_tiers")))
    return (200 if result.get("ok") else 400), result


def _route_test_provider(ctx):
    return 200, {
        "ok": True,
        "result": provider_check.check(str(ctx.body.get("name", "")), lang=ctx.lang),
    }


def _route_preflight(ctx):
    """Call every configured model once, for eight tokens, and remember it.

    A POST, never a GET on a polled path: each probe is a real generation on the
    operator's own account. The doctor reads what this leaves behind and never
    measures — the same split as the hardware bench.
    """
    from . import preflight

    s = _fresh_settings()
    if s.llm_mock:
        return 400, {"ok": False, "error": "mock mode: there is no provider to call"}
    report = preflight.run(s, timeout=int(ctx.body.get("timeout", preflight.TIMEOUT)))
    preflight.save(ctx.state.store(), report)
    return 200, {
        "ok": True,
        **report.as_dict(),
        # What this cannot reach, named rather than dropped: a preflight that
        # covers three of six tiers and reports success is worse than one that
        # admits its reach.
        "skipped": [{"tier": t, "model": m} for t, m in preflight.skipped(s)],
    }


def _route_sweep_get(ctx):
    """Progress of a running sweep, and what is known when none is running.

    A GET, polled by the page — so it reads state and calls nobody. The probing
    happens in the worker thread that the POST started.
    """
    from . import preflight

    known = ctx.state.store().known_probes()
    tally: dict[str, int] = {}
    oldest = 0.0
    for row in known:
        tally[row["state"]] = tally.get(row["state"], 0) + 1
        oldest = max(oldest, time.time() - float(row["ts"] or time.time()))
    return 200, {
        "ok": True,
        "sweep": ctx.state.sweep,
        "known": len(known),
        "tally": tally,
        "usable_by_provider": {k: len(v) for k, v in preflight.known(ctx.state.store()).items()},
        # A verdict is a measurement and measurements age. Shown so nobody reads
        # a six-month-old "blocked" as current fact.
        "oldest_days": int(oldest / 86400),
        "worth_rechecking": len(preflight.stale(ctx.state.store())),
    }


def _route_sweep_post(ctx):
    """Start — or price, or stop — a sweep of every configured provider.

    `{"estimate": true}` returns the number of calls it would make without
    making any. That is deliberate: NVIDIA alone advertises 102 models, and an
    operator pressing "check everything" is spending their own money and their
    own rate limits. They get the number first.
    """
    from . import preflight

    s = _fresh_settings()
    if ctx.body.get("stop"):
        ctx.state.sweep["stop"] = True
        return 200, {"ok": True, "stopping": True}
    if s.llm_mock:
        return 400, {"ok": False, "error": "mock mode: there is no provider to call"}
    if ctx.body.get("estimate"):
        return 200, {"ok": True, **preflight.estimate()}
    with ctx.state.lock:
        if ctx.state.sweep.get("running"):
            return 400, {"ok": False, "error": "a sweep is already running"}
        ctx.state.sweep = {
            "running": True,
            "stop": False,
            "done": 0,
            "provider": "",
            "model": "",
            "counts": {},
        }

    limit = int(ctx.body.get("limit", 0) or 0)
    timeout = int(ctx.body.get("timeout", preflight.TIMEOUT) or preflight.TIMEOUT)
    store = ctx.state.store()

    def _worker() -> None:
        def note(provider, model, result, done):
            sweep = ctx.state.sweep
            sweep["provider"], sweep["model"], sweep["done"] = provider, model, done
            sweep["counts"][result.state] = sweep["counts"].get(result.state, 0) + 1

        try:
            preflight.sweep(
                store,
                limit=limit,
                timeout=timeout,
                on_progress=note,
                should_stop=lambda: bool(ctx.state.sweep.get("stop")),
            )
        except Exception:  # noqa: BLE001 - a background thread must not die silently
            log.exception("sweep failed")
        finally:
            # Everything proved before the failure is already in the store: each
            # verdict is written the moment it arrives, so an hour of real calls
            # is never lost to whatever went wrong at the end.
            ctx.state.sweep["running"] = False

    threading.Thread(target=_worker, daemon=True, name="corparius-preflight-sweep").start()
    return 200, {"ok": True, "started": True}


def _route_ollama_pull(ctx):
    return 200, _ollama_pull(ctx.state, list(ctx.body.get("models", [])))


def _route_company_post(ctx):
    result = _save_company(ctx.state, ctx.slug, dict(ctx.body.get("config", {})))
    return (200 if result.get("ok") else 400), result


def _route_company_delete(ctx):
    result = _delete_company(
        ctx.state, ctx.slug, str(ctx.body.get("confirm", "")), bool(ctx.body.get("purge_store"))
    )
    return (200 if result.get("ok") else 400), result


def _route_chat_post(ctx):
    message = str(ctx.body.get("message", "")).strip()
    if not message:
        return 400, {"ok": False, "error": "empty message"}
    return 200, _chat(ctx.state, ctx.slug, message, ctx.lang)


@dataclass(frozen=True)
class Route:
    """One endpoint.

    `public` defaults to False on purpose, and it is the whole point of this
    table. do_GET and do_POST used to be two independent if/elif chains, and the
    token check lived in one of them only - so every read endpoint was open,
    and nothing in the code made that visible. Here the unsafe choice has to be
    typed out, which makes it greppable and reviewable; adding a route without
    thinking about auth yields an authenticated one.

    `mutating` is derived from the method rather than stored: it is exactly
    true for POST in this API, and one fewer field to get wrong.
    """

    method: str
    path: str
    handler: Callable
    public: bool = False
    needs_slug: bool = False  # no company named -> fall through to 404


# Exact matches, checked first.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", _route_page, public=True),
    Route("GET", "/api/session", _route_session, public=True),
    Route("GET", "/api/companies", _route_companies_get),
    Route("GET", "/api/overview", _route_overview, needs_slug=True),
    Route("GET", "/api/providers", _route_providers_get),
    Route("GET", "/api/golive", _route_golive, needs_slug=True),
    Route("GET", "/api/settings", _route_settings_get),
    Route("GET", "/api/company", _route_company_get, needs_slug=True),
    Route("GET", "/api/ollama", _route_ollama_get),
    Route("GET", "/api/drafts", _route_drafts_get, needs_slug=True),
    Route("GET", "/api/site", _route_site_get, needs_slug=True),
    Route("GET", "/api/payments", _route_payments_get),
    Route("GET", "/api/doctor", _route_doctor),
    Route("GET", "/api/update", _route_update),
    Route("POST", "/api/update/apply", _route_update_apply),
    Route("GET", "/api/plugins", _route_plugins_get),
    Route("GET", "/api/theme", _route_theme_get),
    Route("GET", "/api/chat", _route_chat_get, needs_slug=True),
    Route("POST", "/api/companies", _route_companies_post),
    Route("POST", "/api/approvals", _route_approvals_post),
    Route("POST", "/api/drafts", _route_drafts_post, needs_slug=True),
    Route("POST", "/api/rules", _route_rules_post, needs_slug=True),
    Route("POST", "/api/memory", _route_memory_post),
    Route("POST", "/api/inbox", _route_inbox_post),
    Route("POST", "/api/tasks", _route_tasks_post),
    Route("POST", "/api/site", _route_site_post),
    Route("POST", "/api/deploy", _route_deploy_post),
    Route("POST", "/api/backup", _route_backup_post),
    Route("POST", "/api/run/stop", _route_run_stop),
    Route("POST", "/api/run", _route_run_post),
    Route("POST", "/api/providers", _route_providers_post),
    Route("POST", "/api/tiers/recommend", _route_tiers_recommend),
    Route("POST", "/api/provider/models", _route_provider_models),
    Route("POST", "/api/settings", _route_settings_post),
    Route("POST", "/api/plugins", _route_plugins_post),
    Route("POST", "/api/skills/scope", _route_skill_scope, needs_slug=True),
    Route("POST", "/api/theme", _route_theme_post),
    Route("POST", "/api/test/mail", _route_test_mail),
    Route("POST", "/api/test/payments", _route_test_payments),
    Route("POST", "/api/test/claude", _route_test_claude),
    Route("POST", "/api/claude/setup", _route_claude_setup),
    Route("POST", "/api/claude/install", _route_claude_install),
    Route("POST", "/api/test/provider", _route_test_provider),
    Route("POST", "/api/preflight", _route_preflight),
    Route("GET", "/api/preflight/sweep", _route_sweep_get),
    Route("POST", "/api/preflight/sweep", _route_sweep_post),
    Route("POST", "/api/ollama/pull", _route_ollama_pull),
    Route("POST", "/api/ollama/bench", _route_ollama_bench),
    Route("POST", "/api/company", _route_company_post),
    Route("POST", "/api/company/delete", _route_company_delete),
    Route("POST", "/api/chat", _route_chat_post),
)

# Prefix matches, checked only after every exact route has missed, so /api/site
# can never be shadowed by a prefix that happens to start the same way.
PREFIX_ROUTES: tuple[Route, ...] = (Route("GET", "/site/", _route_site_serve, public=True),)

_EXACT = {(r.method, r.path): r for r in ROUTES}
assert len(_EXACT) == len(ROUTES), "duplicate (method, path) in ROUTES"


def _match(method: str, path: str) -> Route | None:
    route = _EXACT.get((method, path))
    if route is not None:
        return route
    for candidate in PREFIX_ROUTES:
        if candidate.method == method and path.startswith(candidate.path):
            return candidate
    return None


class Handler(BaseHTTPRequestHandler):
    state: UiState  # injected by build_server
    server_version = "corparius-ui"

    def log_message(self, fmt, *args):  # quiet by default, keep the app log
        log.debug("%s " + fmt, self.address_string(), *args)

    def _send(self, code: int, payload: dict | bytes, ctype="application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict:
        # Chunked bodies are not decoded by http.server, so Content-Length is
        # absent and the ceiling below would be trivially bypassable. The page
        # never sends chunked; refusing is safer than reading an unbounded body.
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            raise _RequestRefused(411, "chunked bodies are not accepted")
        raw = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw)
        except ValueError:
            # Attacker-controlled: int() used to raise inside the handler and
            # surface as a 500 rather than a 400.
            raise _RequestRefused(400, "malformed Content-Length") from None
        if length < 0:
            raise _RequestRefused(400, "malformed Content-Length")
        if length > MAX_BODY:
            # Refused without reading, which deliberately breaks the
            # read-before-refuse rule documented in _dispatch. That rule exists
            # so the page reliably sees a 401; it does not need to hold for a
            # client announcing four gigabytes, and honouring it there is the
            # denial of service. Do not "fix" this back.
            raise _RequestRefused(413, f"body larger than {MAX_BODY} bytes")
        if not length:
            return {}
        try:
            parsed = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}
        # A body that is valid JSON but not an object ([], 123, "x", null) would
        # make the handler's body.get(...) raise AttributeError and surface as a
        # 500. Treat it as no fields, the same as an empty body.
        return parsed if isinstance(parsed, dict) else {}

    def _authorized(self) -> bool:
        token = cfg.get("CORP_UI_TOKEN", "").strip()
        if not token:
            return True  # no token configured: the zero-config local default
        supplied = self.headers.get("X-Corp-Token", "")
        # compare_digest wants two byte strings and raises on non-ASCII str.
        return hmac.compare_digest(token.encode("utf-8"), supplied.encode("utf-8", "replace"))

    def _host_allowed(self) -> bool:
        """Reject a request whose Host is not one this console answers to.

        This is the DNS-rebinding defence, and it is a different check from the
        Origin one below. If evil.com rebinds its A record to 127.0.0.1, the
        browser treats the request as same-origin and sends a matching Origin,
        so the Origin check passes. What does not match is the console's own
        identity: the request still arrives with Host: evil.com.
        """
        host = _host_only(self.headers.get("Host") or "")
        allowed = {
            h.strip().lower() for h in cfg.get("CORP_UI_ALLOWED_HOSTS", "").split(",") if h.strip()
        }
        if allowed:
            return host in allowed
        bind = _fresh_settings().ui_host
        if bind not in _LOOPBACK:
            # Bound off-loopback means Docker or a reverse proxy, where the
            # operator's real hostname is unknown to us. A strict default would
            # break every existing deployment on upgrade, so permit and let
            # CORP_UI_ALLOWED_HOSTS narrow it. doctor already fails this case
            # when no token is set.
            return True
        return host in _LOOPBACK or not host

    def _same_origin(self) -> bool:
        """Reject a cross-site write.

        Three tiers, in order. Both headers are on the browser's forbidden list,
        so a page on evil.com cannot set or spoof either one.

        1. Sec-Fetch-Site, which current browsers always send. `none` is a
           bookmark or the address bar; `same-origin` is our own page.
        2. Origin, compared against the Host we were reached on.
        3. Neither present: not a browser. Allowed - this is what keeps curl,
           the CI smoke job, the test suite's HTTPConnection and the MCP server
           working with no configuration. The token check still applies to them
           independently.

        Tier 1 is also what blocks a plain <form> POST from a malicious page -
        the classic no-JS CSRF - without a CSRF token, a cookie, or a login
        screen, which the console deliberately refuses to be.
        """
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if site:
            return site in ("same-origin", "none")
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        if not parsed.netloc:
            return False  # "null" origin: a sandboxed iframe or a file:// page
        return parsed.netloc.lower() == (self.headers.get("Host") or "").strip().lower()

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        lang = ""
        try:
            # Host first, on every request including GET: it costs nothing and
            # a rebound name should not reach a handler at all.
            if not self._host_allowed():
                log.warning(
                    "refused Host %r (set CORP_UI_ALLOWED_HOSTS to allow it)",
                    self.headers.get("Host"),
                )
                self._send(
                    403,
                    {
                        "ok": False,
                        "error": "Host not allowed. If you reach this console through a "
                        "proxy or another name, list it in CORP_UI_ALLOWED_HOSTS "
                        "(comma separated) and restart.",
                    },
                )
                return
            # POST carries its parameters in the body; GET has none to read. The
            # body is read before auth is decided, even when we are about to
            # refuse: closing the connection on an unread body makes the client
            # see a reset instead of our 401, and the page needs the 401 to know
            # it should ask for a token.
            body = self._json_body() if method == "POST" else {}
            source = body if method == "POST" else query
            lang = str(source.get("lang", ""))
            route = _match(method, url.path)
            slug = str(source.get("company", ""))
            if route is None or (route.needs_slug and not slug):
                self._send(404, {"ok": False, "error": "not found"})
                return
            # Writes must come from our own page. Reads are exempt: they carry
            # no side effect, and a cross-site reader cannot see the response
            # anyway without CORS, which is never granted.
            if method == "POST" and not self._same_origin():
                log.warning(
                    "refused cross-site POST %s from Origin %r",
                    url.path,
                    self.headers.get("Origin"),
                )
                self._send(403, {"ok": False, "error": "cross-site request refused"})
                return
            # One check, both verbs, driven by the route's own `public` flag.
            # This used to run in do_POST only, which left every read endpoint
            # open even when the operator had configured a token.
            if not route.public and not self._authorized():
                self._send(401, {"ok": False, "error": "missing or wrong X-Corp-Token"})
                return
            ctx = Ctx(state=self.state, path=url.path, query=query, body=body, slug=slug, lang=lang)
            self._send(*route.handler(ctx))
        except _RequestRefused as refused:
            self._send(refused.status, {"ok": False, "error": refused.message})
        except Exception:
            log.exception("%s %s failed", method, self.path)
            self._send(500, {"ok": False, "error": _oops(lang)})

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")


def build_server(
    settings: Settings,
    host: str | None = None,
    port: int | None = None,
    env_file: Path | None = None,
) -> ThreadingHTTPServer:
    path = env_file or ROOT / ".env"
    cfg.set_dotenv_path(path)  # the console and the resolver must agree on it
    state = UiState(settings, path)
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer(
        (host or settings.ui_host, settings.ui_port if port is None else port), handler
    )


def _port_in_use(host: str, port: int) -> bool:
    """Probe before binding. allow_reuse_address lets a second bind quietly
    succeed on some platforms (Windows especially), so checking the bind result
    is not reliable; a connection that answers is."""
    import socket

    probe = "127.0.0.1" if host in ("", "0.0.0.0") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex((probe, port)) == 0
        except OSError:
            return False


def serve(settings: Settings, host: str | None = None, port: int | None = None) -> int:
    from . import plugins

    plugins.load()  # no-op unless CORP_PLUGINS_ENABLED; extends the registries
    want = settings.ui_port if port is None else port
    host = host or settings.ui_host
    if _port_in_use(host, want):
        print(
            f"corparius: port {want} is already in use. Another console may be "
            f"running (open http://127.0.0.1:{want}), or pick a free port: "
            f"python -m corparius.cli ui --port 8601  (or set CORP_UI_PORT)."
        )
        return 1
    try:
        server = build_server(settings, host, port)
    except OSError as exc:
        print(f"corparius: could not start the console on {host}:{want}: {exc}")
        return 1
    bound = server.socket.getsockname()
    log.info("operator console on http://%s:%d (Ctrl+C to stop)", bound[0], bound[1])
    print(f"corparius console: http://{bound[0]}:{bound[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        _drain_and_close(server.RequestHandlerClass.state)  # type: ignore[attr-defined]  # injected in build_server
    return 0


def _drain_and_close(state: UiState, join_timeout: float = 5.0) -> None:
    """Stop any in-flight run, let it unwind, then close the store.

    A --loop run checks should_stop() at the top of each tick but still banks the
    day with a save_state() afterwards, so closing the connection out from under
    it would make that final write hit a closed database. Signal every run, join
    the daemon workers briefly, then close - the connection outlives the request
    that opened it, and on Windows nothing can move or delete the store while it
    is open."""
    for run in list(state.runs.values()):
        ev = run.get("stop")
        if ev is not None:
            ev.set()
    for t in threading.enumerate():
        if t.name.startswith("corparius-run-"):
            t.join(timeout=join_timeout)
    state.close()

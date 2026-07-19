"""Local operator console. A stdlib HTTP server (no new dependency) serves a
single-file page (webui.html) and a small JSON API over the same Store,
Runtime and HybridRouter the CLI uses.

Scope and safety: binds to 127.0.0.1 by default. Set CORP_UI_TOKEN to require
the X-Corp-Token header on every mutating call (useful behind a reverse proxy);
the doctor fails when the console is bound off-localhost without one.

Settings saved from the page go to the store, or to .env for the bootstrap keys
that must be readable before the store opens; see app/cfg.py for the precedence.
Secrets are write-only: the API only ever reports whether one is set.
"""
from __future__ import annotations
import json
import logging
import os
import re
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from . import backup, cfg, claudecli, deploy, i18n, mailbox, ollama_setup, paths
from . import provider_check, settings_spec, structured
from . import company as company_mod
from .agents import ROSTER
from .tools import TOOLS
from .doctor import run_checks
from .config import Settings
from .integrations import smtp_check, stripe_check, stripe_payments
from .llm import OPENAI_COMPAT_PROVIDERS, HybridRouter
from .models import AgentRole, Difficulty
from .orchestrator import Runtime
from . import sitegen
from .store import Store

log = logging.getLogger("corparius.webui")

# Writable home (for the .env the console writes); a shipped resource for the
# single-file console HTML. Both resolve to the repository layout from a source
# checkout and to the frozen bundle when packaged. Kept as module attributes so
# the tests can monkeypatch them.
ROOT = paths.user_home()
PAGE = paths.page_file()

# Environment variables the page may set. Anything else is refused.
_TOGGLES = {"CORP_CLOUD_ENABLED", "CORP_LLM_MOCK", "CORP_CLAUDE_CODE"}
_TIERS = {"CORP_TRIVIAL_MODEL", "CORP_NORMAL_MODEL", "CORP_HARD_MODEL",
          "CORP_LLM_FALLBACK", "CORP_LOCAL_MODEL"}
_KEYS = ({spec["key_env"] for spec in OPENAI_COMPAT_PROVIDERS.values()}
         | {spec["base_env"] for spec in OPENAI_COMPAT_PROVIDERS.values() if "base_env" in spec}
         | {"ANTHROPIC_API_KEY"})
# Everything the page may write: the provider panel's vars plus every row of the
# settings registry. Anything else is refused.
ALLOWED_VARS = settings_spec.WRITABLE
# Stored write-only: never returned by the API, only a "configured" boolean.
_SECRET_VARS = settings_spec.SECRETS

_CHAT_LIMIT = 30  # turns kept per company, in-process only


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
    ones. Comments and unrelated lines are left untouched."""
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
        self.pulls: dict = {"running": False}   # Ollama model pull, background
        self.lock = threading.Lock()

    def store(self) -> Store:
        return Store(self.settings.data_path)


def _overview(state: UiState, slug: str) -> dict:
    store = state.store()
    st = store.status(slug)
    flow = store.flow_metrics(slug)
    tasks = store.list_tasks(slug)
    tick = int(store.load_state(slug).get("tick", 0))
    spend = store.db.execute(
        "SELECT agent, COALESCE(SUM(input_tokens+output_tokens),0) t "
        "FROM token_usage WHERE company=? GROUP BY agent ORDER BY t DESC", (slug,)).fetchall()
    actions = store.db.execute(
        "SELECT agent, tool, ok, ts, substr(output,1,160) output FROM actions "
        "WHERE company=? ORDER BY id DESC LIMIT 25", (slug,)).fetchall()
    frozen = store.db.execute(
        "SELECT COUNT(*) n FROM actions WHERE company=? AND tool='circuit_breaker_freeze'",
        (slug,)).fetchone()["n"]
    approvals = store.list_approvals(slug, "pending")
    for a in approvals:  # parameters are stored as a JSON string
        if isinstance(a.get("parameters"), str):
            try:
                a["parameters"] = json.loads(a["parameters"])
            except json.JSONDecodeError:
                pass
    s = _fresh_settings()
    run = state.runs.get(slug, {})
    by_status: dict[str, list] = {"proposed": [], "approved": [], "in_progress": [], "done": []}
    for t in tasks:
        by_status.setdefault(t["status"], []).append(t)
    return {
        "ok": True, "company": slug, "tick": tick, "status": st, "flow": flow,
        "tasks": by_status,
        "approvals": approvals,
        "spend_by_agent": [dict(r) for r in spend],
        "recent_actions": [dict(r) for r in actions],
        "freezes": frozen,
        "session_budget": s.session_token_budget,
        "llm_mock": s.llm_mock, "cloud_enabled": s.cloud_enabled,
        "running": bool(run.get("running")), "last_run": run.get("result"),
        "loop": bool(run.get("loop")),
        "stopping": bool(run.get("running") and run.get("stop") and run["stop"].is_set()),
    }


def _providers_payload() -> dict:
    s = _fresh_settings()
    providers = []
    for name, spec in sorted(OPENAI_COMPAT_PROVIDERS.items()):
        key = cfg.get(spec["key_env"], "").strip()
        base = cfg.get(spec.get("base_env", ""), "").strip() or spec["base"]
        providers.append({
            "name": name, "key_env": spec["key_env"], "base_env": spec.get("base_env"),
            "base": base, "key_optional": bool(spec.get("key_optional")),
            "configured": bool(key) or (bool(spec.get("key_optional")) and bool(base)),
            "key_set": bool(key),
        })
    return {
        "ok": True, "providers": providers,
        "anthropic_key_set": bool(cfg.get("ANTHROPIC_API_KEY", "").strip()),
        "claude_code": s.claude_code_enabled,
        "claude_installed": claudecli.installed(),
        "claude_ready": claudecli.already_on(),
        "server_presets": settings_spec.LLM_SERVER_PRESETS,
        "cloud_enabled": s.cloud_enabled, "llm_mock": s.llm_mock,
        "tiers": {"trivial": s.trivial_model, "normal": s.normal_model,
                  "hard": s.hard_model, "local_fallback": s.local_model,
                  "fallback_chain": ",".join(s.llm_fallback)},
    }


# What the CEO chat can propose. Each maps to an existing, audited endpoint the
# operator confirms with a click, so the chat never mutates on its own and money
# or production still passes the HITL gate on the resulting run. The LLM only
# routes intent; it opens no new path.
_CEO_ACTIONS = {
    "run_day": {"endpoint": "/api/run", "body": {"ticks": 24}, "label_en": "Run a day",
                "label_fr": "Lancer une journée"},
    "run_loop": {"endpoint": "/api/run", "body": {"ticks": 24, "loop": True},
                 "label_en": "Run continuously", "label_fr": "Lancer en continu"},
    "deploy": {"endpoint": "/api/deploy", "body": {}, "label_en": "Publish the site",
               "label_fr": "Publier le site"},
    "build_site": {"endpoint": "/api/site", "body": {}, "label_en": "Build the site",
                   "label_fr": "Générer le site"},
    "backup": {"endpoint": "/api/backup", "body": {}, "label_en": "Back up now",
               "label_fr": "Sauvegarder"},
    "use_claude": {"endpoint": "/api/claude/setup", "body": {}, "no_company": True,
                   "label_en": "Use my Claude subscription", "label_fr": "Utiliser mon abonnement Claude"},
}

_CEO_SCHEMA = {
    "reply": {"type": "str", "required": True, "max_len": 800},
    "intent": {"type": "str", "default": "answer",
               "choices": ["answer"] + list(_CEO_ACTIONS)},
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
        + ("; ".join(t["title"] for t in open_tasks) or "none") + "."
    )
    system = (
        f"{spec.system_prompt} You are chatting with your human operator through "
        f"the corparius console. Be concise and concrete; reference the snapshot "
        f"when relevant. Write 'reply' in {'French' if lang == 'fr' else 'English'}. "
        f"Set 'intent' to one of {', '.join(_CEO_ACTIONS)} ONLY when the operator is "
        f"clearly asking to do that thing now; otherwise 'answer'. You never execute; "
        f"the operator confirms with a button. {snapshot}"
    )
    history = state.chats.setdefault(slug, deque(maxlen=_CHAT_LIMIT))
    messages = ([{"role": "system", "content": system}]
                + [{"role": m["role"], "content": m["text"]} for m in history]
                + [{"role": "user", "content": message}])
    # One structured call classifies intent and writes the reply. The harness
    # returns the same shape whatever model answered; in mock or on a weak model
    # it falls back to intent=answer, so the chat degrades to plain conversation.
    router = HybridRouter(_fresh_settings())
    result = structured.ask(router, messages, _CEO_SCHEMA, difficulty=spec.difficulty)
    for u in result.usages:
        store.record_usage(slug, "ceo", u.input_tokens, u.output_tokens)
    reply = result.data.get("reply") or message
    intent = result.data.get("intent", "answer")
    proposal = None
    if intent in _CEO_ACTIONS and not result.fell_back:
        spec_a = dict(_CEO_ACTIONS[intent])
        body = dict(spec_a["body"])
        if intent == "run_day":
            body["ticks"] = max(1, min(int(result.data.get("ticks", 24)), 48))
        proposal = {"intent": intent, "endpoint": spec_a["endpoint"], "body": body,
                    "needs_company": not spec_a.get("no_company"),
                    "label": i18n.pick(lang, spec_a["label_en"], spec_a["label_fr"])}
    provider, _, model = result.source.partition(":")   # "mock:haiku" -> mock, haiku
    history.append({"role": "user", "text": message})
    history.append({"role": "assistant", "text": reply, "model": model, "provider": provider})
    return {"ok": True, "reply": reply, "model": model, "provider": provider,
            "proposal": proposal, "history": list(history)}


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
            state.runs[slug] = {"running": False, "result": {"error": i18n.pick(lang,
                "The run stopped on an unexpected error. See the server log for details.",
                "Le run s'est arrêté sur une erreur inattendue. Voir le journal du serveur.")}}

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


_DEFAULT_AGENTS = company_mod.DEFAULT_AGENTS   # kept: the wizard's checkbox list


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
    cfg, errors, warnings = company_mod.validate({
        "name": body.get("name", ""),
        "one_liner": body.get("one_liner", ""),
        "offer": offer,
        "icp": icp,
        "agents": agents,
        "budgets": {"session_tokens": body.get("session_tokens", 80000)},
    })
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    path = company_mod.path_for(cfg["slug"])
    if path.exists():
        return {"ok": False, "error": f"company '{cfg['slug']}' already exists"}
    company_mod.dump(cfg, path)
    state.store().save_state(cfg["slug"], {"tick": 0})
    log.info("company created from the console: %s", cfg["slug"])
    return {"ok": True, "slug": cfg["slug"], "companies": _companies(),
            "warnings": warnings}


def _company_payload(slug: str) -> dict:
    cfg = _load_company(slug)
    if cfg is None:
        return {"ok": False, "error": f"unknown company '{slug}'"}
    # A broken file opens in the editor with its problems named, rather than
    # returning a 404 that strands the operator with nothing to fix it from.
    _cfg, errors, warnings = company_mod.validate(cfg)
    return {"ok": True, "company": cfg, "path": str(company_mod.path_for(slug)),
            "warnings": warnings, "problems": errors, "roles": list(company_mod.ROLES),
            "channels": list(company_mod.CHANNELS), "billing": list(company_mod.BILLING),
            "tools": sorted(TOOLS)}


def _save_company(state: UiState, slug: str, body: dict) -> dict:
    if slug not in _companies():
        return {"ok": False, "error": f"unknown company '{slug}'"}
    incoming = dict(body or {})
    incoming["slug"] = slug          # the slug is the directory; renaming is a move, not an edit
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
    return {"ok": True, "companies": _companies(), "trashed": str(dest),
            "purged": bool(purge)}


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
            _merge_env_file(state.env_file,
                            {k: "" for k in unset if k in cfg.BOOTSTRAP})
    cfg.invalidate()
    meta: dict = {}
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
        task_id = int(body.get("id"))
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
        sitegen.build_site(company, str(out_dir))
    res = deploy.deploy_result(str(out_dir))
    # The envelope succeeded; whether anything published is the payload's news.
    return 200, {"ok": True, "published": res["ok"], "provider": res["provider"],
                 "result": res["result"], "errors": res["errors"], "skipped": res["skipped"]}


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


def _claude_setup(state: UiState) -> dict:
    """One press: prove the CLI works, then flip mock off, cloud on, Claude Code
    on, and point the tiers at claudecode. The four scattered settings and the
    hand-edited tier strings were most of the friction."""
    result = claudecli.check()
    if not result["ok"]:
        # Do not switch a company to a provider that will not answer.
        return {"ok": False, "error": result["detail"], "check": result}
    _persist(state, claudecli.plan())
    payload = _providers_payload()
    return {**payload, "check": result, "applied": claudecli.plan()}


def _oops(lang: str = "en") -> str:
    """The message for an unexpected error. The full traceback goes to the server
    log; the operator gets a sentence, not Python internals."""
    return i18n.pick(lang,
        "Something went wrong on the console. The details are in the server log.",
        "Un problème est survenu dans la console. Les détails sont dans le journal du serveur.")


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
        return {"ok": False,
                "detail": i18n.pick(lang,
                    "No mail account set yet. Pick a provider above, give the address "
                    "and an app password.",
                    "Aucun compte mail réglé. Choisissez un fournisseur ci-dessus, donnez "
                    "l'adresse et un mot de passe d'application.")}
    return {"ok": bool(send["ok"] and read["ok"]),
            "send_ok": send["ok"], "read_ok": read["ok"],
            "detail": "\n".join(lines)}


def _settings_payload() -> dict:
    return {
        "ok": True,
        "groups": settings_spec.GROUPS,
        "fields": [settings_spec.describe(f.key) for f in settings_spec.SPEC],
        "warning": {"en": settings_spec.WARN_EN, "fr": settings_spec.WARN_FR},
        "mail_presets": settings_spec.MAIL_PRESETS,
    }


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
            plugins.install_from_registry(name)   # verified only from the console
        else:
            return {"ok": False, "error": f"unknown action '{action}'"}
    except plugins.PluginError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "restart_required": True, **plugins.status()}


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
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _authorized(self) -> bool:
        token = cfg.get("CORP_UI_TOKEN", "").strip()
        return not token or self.headers.get("X-Corp-Token", "") == token

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        slug = q.get("company", "")
        try:
            if url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html")
            elif url.path == "/api/companies":
                self._send(200, {"ok": True, "companies": _companies(),
                                 "templates": company_mod.TEMPLATES})
            elif url.path == "/api/overview" and slug:
                self._send(200, _overview(self.state, slug))
            elif url.path == "/api/providers":
                self._send(200, _providers_payload())
            elif url.path == "/api/settings":
                self._send(200, _settings_payload())
            elif url.path == "/api/company" and slug:
                result = _company_payload(slug)
                self._send(200 if result["ok"] else 404, result)
            elif url.path == "/api/session":
                # Tells the page whether it must send X-Corp-Token. It never
                # serves the token itself.
                self._send(200, {"ok": True,
                                 "token_required": bool(cfg.get("CORP_UI_TOKEN", "").strip())})
            elif url.path == "/api/ollama":
                result = ollama_setup.status(lang=q.get("lang", ""))
                pulls = self.state.pulls
                if pulls.get("running"):
                    result = {**result, "detail": pulls.get("progress") or "pulling...",
                              "pulling": True}
                self._send(200, {"ok": True, "result": result})
            elif url.path == "/api/site" and slug:
                site = paths.site_index(_fresh_settings().data_path, slug)
                self._send(200, {"ok": True, "built": site.is_file(),
                                 "mtime": site.stat().st_mtime if site.is_file() else None})
            elif url.path.startswith("/site/"):
                slug2 = url.path.split("/")[2] if len(url.path.split("/")) > 2 else ""
                site = paths.site_index(_fresh_settings().data_path, slug2)
                if slug2 in _companies() and site.is_file():
                    self._send(200, site.read_bytes(), "text/html")
                else:
                    self._send(404, {"ok": False, "error": "site not built yet"})
            elif url.path == "/api/payments":
                self._send(200, {"ok": True, **stripe_payments()})
            elif url.path == "/api/doctor":
                self._send(200, {"ok": True, "checks": run_checks(_fresh_settings())})
            elif url.path == "/api/update":
                # Off unless CORP_UPDATE_CHECK is on; when off this makes no
                # network call. See app/update_check.py.
                from . import update_check
                self._send(200, {"ok": True, **update_check.check()})
            elif url.path == "/api/plugins":
                from . import plugins
                self._send(200, {"ok": True, **plugins.status()})
            elif url.path == "/api/chat" and slug:
                history = list(self.state.chats.get(slug, []))
                self._send(200, {"ok": True, "history": history})
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception:
            log.exception("GET %s failed", self.path)
            self._send(500, {"ok": False, "error": _oops(q.get("lang", ""))})

    def do_POST(self) -> None:  # noqa: N802
        # Read the body before deciding anything, even when we are about to
        # refuse. Closing the connection on an unread body makes the client see
        # a reset instead of our 401, and the page needs the 401 to know it
        # should ask for a token.
        body = self._json_body()
        if not self._authorized():
            self._send(401, {"ok": False, "error": "missing or wrong X-Corp-Token"})
            return
        url = urlparse(self.path)
        slug = str(body.get("company", ""))
        store = self.state.store()
        try:
            if url.path == "/api/companies":
                self._send(200, _create_company(self.state, body))
            elif url.path == "/api/approvals":
                decision = body.get("decision")
                if decision not in ("approved", "rejected"):
                    self._send(400, {"ok": False, "error": "decision must be approved or rejected"})
                    return
                done = store.set_approval_status(
                    str(body.get("id")), decision, str(body.get("note", "via console")))
                self._send(200 if done else 404,
                           {"ok": done, "error": None if done else "approval not found"})
            elif url.path == "/api/tasks":
                self._send(*_edit_task(store, body))
            elif url.path == "/api/site":
                company = _load_company(slug)
                if company is None:
                    self._send(404, {"ok": False, "error": f"unknown company '{slug}'"})
                    return
                out_dir = paths.site_dir(_fresh_settings().data_path, slug)
                headline = str(body.get("headline", "")).strip()
                sitegen.build_site(company, str(out_dir), headline=headline or None)
                self._send(200, {"ok": True, "built": True})
            elif url.path == "/api/deploy":
                self._send(*_deploy(self.state, slug))
            elif url.path == "/api/backup":
                path = backup.make_backup(_fresh_settings().data_path)
                self._send(200, {"ok": True, "name": path.name,
                                 "size": path.stat().st_size,
                                 "warning": {"en": backup.WARNING_EN, "fr": backup.WARNING_FR}})
            elif url.path == "/api/run/stop":
                self._send(200, _stop_run(self.state, slug))
            elif url.path == "/api/run":
                ticks = max(1, min(int(body.get("ticks", 6)), 48))
                self._send(200, _start_run(self.state, slug, ticks,
                                           loop=bool(body.get("loop")),
                                           lang=str(body.get("lang", ""))))
            elif url.path == "/api/providers":
                self._send(200, _set_env(self.state, dict(body.get("values", {}))))
            elif url.path == "/api/settings":
                result = _set_settings(self.state, dict(body.get("values", {})),
                                       list(body.get("unset", [])))
                self._send(200 if result.get("ok") else 400, result)
            elif url.path == "/api/plugins":
                result = _plugins_action(body)
                self._send(200 if result.get("ok") else 400, result)
            elif url.path == "/api/test/mail":
                # One button, both directions. A real send and a real read:
                # setting a mail account and hoping is the friction, and this is
                # the answer to "did it work?".
                self._send(200, {"ok": True, "result": _mail_check(str(body.get("to", "")),
                                                                   str(body.get("lang", "")))})
            elif url.path == "/api/test/payments":
                self._send(200, {"ok": True, "result": stripe_check(lang=str(body.get("lang", "")))})
            elif url.path == "/api/test/claude":
                self._send(200, {"ok": True, "result": claudecli.check(lang=str(body.get("lang", "")))})
            elif url.path == "/api/claude/setup":
                result = _claude_setup(self.state)
                self._send(200 if result.get("ok") else 400, result)
            elif url.path == "/api/test/provider":
                self._send(200, {"ok": True,
                                 "result": provider_check.check(str(body.get("name", "")),
                                                                lang=str(body.get("lang", "")))})
            elif url.path == "/api/ollama/pull":
                self._send(200, _ollama_pull(self.state, list(body.get("models", []))))
            elif url.path == "/api/company":
                result = _save_company(self.state, slug, dict(body.get("config", {})))
                self._send(200 if result.get("ok") else 400, result)
            elif url.path == "/api/company/delete":
                result = _delete_company(self.state, slug, str(body.get("confirm", "")),
                                         bool(body.get("purge_store")))
                self._send(200 if result.get("ok") else 400, result)
            elif url.path == "/api/chat":
                message = str(body.get("message", "")).strip()
                if not message:
                    self._send(400, {"ok": False, "error": "empty message"})
                    return
                self._send(200, _chat(self.state, slug, message, str(body.get("lang", ""))))
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception:
            log.exception("POST %s failed", self.path)
            self._send(500, {"ok": False, "error": _oops(str(body.get("lang", "")))})


def build_server(settings: Settings, host: str | None = None, port: int | None = None,
                 env_file: Path | None = None) -> ThreadingHTTPServer:
    path = env_file or ROOT / ".env"
    cfg.set_dotenv_path(path)   # the console and the resolver must agree on it
    state = UiState(settings, path)
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((host or settings.ui_host, settings.ui_port if port is None else port), handler)


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
    plugins.load()   # no-op unless CORP_PLUGINS_ENABLED; extends the registries
    want = settings.ui_port if port is None else port
    host = host or settings.ui_host
    if _port_in_use(host, want):
        print(f"corparius: port {want} is already in use. Another console may be "
              f"running (open http://127.0.0.1:{want}), or pick a free port: "
              f"python -m app.cli ui --port 8601  (or set CORP_UI_PORT).")
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
    return 0

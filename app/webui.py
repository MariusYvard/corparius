"""Local operator console. A stdlib HTTP server (no new dependency) serves a
single-file page (webui.html) and a small JSON API over the same Store,
Runtime and HybridRouter the CLI uses.

Scope and safety: binds to 127.0.0.1 by default. Set CORP_UI_TOKEN to require
the X-Corp-Token header on every mutating call (useful behind a reverse
proxy). Provider keys posted from the page are write-only: they are applied to
the running process and persisted to the .env file, and the API only ever
reports whether a key is set, never its value.
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

from .agents import ROSTER
from .doctor import run_checks
from .config import Settings
from .llm import OPENAI_COMPAT_PROVIDERS, HybridRouter
from .models import AgentRole, Difficulty
from .orchestrator import Runtime
from .store import Store

log = logging.getLogger("corparius.webui")

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "webui.html"

# Environment variables the page may set. Anything else is refused.
_TOGGLES = {"CORP_CLOUD_ENABLED", "CORP_LLM_MOCK", "CORP_CLAUDE_CODE"}
_TIERS = {"CORP_TRIVIAL_MODEL", "CORP_NORMAL_MODEL", "CORP_HARD_MODEL",
          "CORP_LLM_FALLBACK", "CORP_LOCAL_MODEL"}
_KEYS = ({spec["key_env"] for spec in OPENAI_COMPAT_PROVIDERS.values()}
         | {spec["base_env"] for spec in OPENAI_COMPAT_PROVIDERS.values() if "base_env" in spec}
         | {"ANTHROPIC_API_KEY"})
ALLOWED_VARS = _TOGGLES | _TIERS | _KEYS

_CHAT_LIMIT = 30  # turns kept per company, in-process only


def _fresh_settings() -> Settings:
    """Settings are read from the environment at construction time, so a new
    instance picks up keys and toggles saved from the page."""
    return Settings()


def _companies() -> list[str]:
    base = ROOT / "companies"
    if not base.is_dir():
        return []
    return sorted(p.parent.name for p in base.glob("*/company.yaml"))


def _load_company(slug: str) -> dict | None:
    path = ROOT / "companies" / slug / "company.yaml"
    if not path.is_file() or slug not in _companies():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg.setdefault("slug", slug)
    return cfg


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
    }


def _providers_payload() -> dict:
    s = _fresh_settings()
    providers = []
    for name, spec in sorted(OPENAI_COMPAT_PROVIDERS.items()):
        key = os.environ.get(spec["key_env"], "").strip()
        base = os.environ.get(spec.get("base_env", ""), "").strip() or spec["base"]
        providers.append({
            "name": name, "key_env": spec["key_env"], "base_env": spec.get("base_env"),
            "base": base, "key_optional": bool(spec.get("key_optional")),
            "configured": bool(key) or (bool(spec.get("key_optional")) and bool(base)),
            "key_set": bool(key),
        })
    return {
        "ok": True, "providers": providers,
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "claude_code": s.claude_code_enabled,
        "cloud_enabled": s.cloud_enabled, "llm_mock": s.llm_mock,
        "tiers": {"trivial": s.trivial_model, "normal": s.normal_model,
                  "hard": s.hard_model, "local_fallback": s.local_model,
                  "fallback_chain": ",".join(s.llm_fallback)},
    }


def _chat(state: UiState, slug: str, message: str) -> dict:
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
        f"when relevant. {snapshot}"
    )
    history = state.chats.setdefault(slug, deque(maxlen=_CHAT_LIMIT))
    messages = ([{"role": "system", "content": system}]
                + [{"role": m["role"], "content": m["text"]} for m in history]
                + [{"role": "user", "content": message}])
    router = HybridRouter(_fresh_settings())
    res = router.generate(messages, difficulty=spec.difficulty, max_tokens=700)
    store.record_usage(slug, "ceo", res.usage.input_tokens, res.usage.output_tokens)
    history.append({"role": "user", "text": message})
    history.append({"role": "assistant", "text": res.text,
                    "model": res.model, "provider": res.provider})
    return {"ok": True, "reply": res.text, "model": res.model,
            "provider": res.provider, "history": list(history)}


def _start_run(state: UiState, slug: str, ticks: int) -> dict:
    cfg = _load_company(slug)
    if cfg is None:
        return {"ok": False, "error": f"unknown company '{slug}'"}
    with state.lock:
        if state.runs.get(slug, {}).get("running"):
            return {"ok": False, "error": "a run is already in progress"}
        state.runs[slug] = {"running": True, "result": None}

    def _worker() -> None:
        try:
            runtime = Runtime(_fresh_settings(), state.store())
            result = runtime.run(cfg, ticks=ticks)
            state.runs[slug] = {"running": False, "result": result}
        except Exception as exc:  # surface, never swallow
            log.exception("run failed for %s", slug)
            state.runs[slug] = {"running": False, "result": {"error": str(exc)}}

    threading.Thread(target=_worker, daemon=True, name=f"corparius-run-{slug}").start()
    return {"ok": True, "running": True}


_DEFAULT_AGENTS = {"ceo": True, "social": True, "outreach": True, "support": True,
                   "ads": False, "finance": True, "strategy": True,
                   "competitor": True, "design": True, "coder": False}


def _create_company(state: UiState, body: dict) -> dict:
    name = str(body.get("name", "")).strip()
    product = str(body.get("product", "")).strip()
    if not name or not product:
        return {"ok": False, "error": "name and product are required"}
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    if not slug:
        return {"ok": False, "error": "the name must contain letters or digits"}
    path = ROOT / "companies" / slug / "company.yaml"
    if path.exists():
        return {"ok": False, "error": f"company '{slug}' already exists"}
    agents = dict(_DEFAULT_AGENTS)
    for role, on in dict(body.get("agents", {})).items():
        if role in agents:
            agents[role] = bool(on)
    try:
        budget = max(1000, min(int(body.get("session_tokens", 80000)), 5_000_000))
    except (TypeError, ValueError):
        budget = 80000
    cfg = {
        "slug": slug, "name": name,
        "one_liner": str(body.get("one_liner", "")).strip() or product,
        "offer": {"product": product, "price_eur": 0, "billing": "stripe", "payment_link": ""},
        "icp": {"segment": str(body.get("segment", "")).strip() or "To be defined",
                "channels": ["linkedin", "x"], "pains": []},
        "agents": agents,
        "budgets": {"session_tokens": budget,
                    "tokens_per_minute": max(1000, budget // 10),
                    "daily_ad_spend_eur": 0},
        "hitl_tools": ["send_financial_transaction", "publish_production_code", "deploy_site"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    state.store().save_state(slug, {"tick": 0})
    log.info("company created from the console: %s", slug)
    return {"ok": True, "slug": slug, "companies": _companies()}


def _set_env(state: UiState, values: dict) -> dict:
    clean: dict[str, str] = {}
    for key, value in values.items():
        if key not in ALLOWED_VARS:
            return {"ok": False, "error": f"variable '{key}' is not settable"}
        clean[key] = str(value).strip()
    for key, value in clean.items():
        os.environ[key] = value
    _merge_env_file(state.env_file, clean)
    return _providers_payload()


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
        token = os.environ.get("CORP_UI_TOKEN", "").strip()
        return not token or self.headers.get("X-Corp-Token", "") == token

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        slug = q.get("company", "")
        try:
            if url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html")
            elif url.path == "/api/companies":
                self._send(200, {"ok": True, "companies": _companies()})
            elif url.path == "/api/overview" and slug:
                self._send(200, _overview(self.state, slug))
            elif url.path == "/api/providers":
                self._send(200, _providers_payload())
            elif url.path == "/api/doctor":
                self._send(200, {"ok": True, "checks": run_checks(_fresh_settings())})
            elif url.path == "/api/chat" and slug:
                history = list(self.state.chats.get(slug, []))
                self._send(200, {"ok": True, "history": history})
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            log.exception("GET %s failed", self.path)
            self._send(500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"ok": False, "error": "missing or wrong X-Corp-Token"})
            return
        url = urlparse(self.path)
        body = self._json_body()
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
                decision = body.get("decision")
                if decision not in ("approved", "rejected"):
                    self._send(400, {"ok": False, "error": "decision must be approved or rejected"})
                    return
                store.set_task_status(int(body.get("id")), decision, "via console")
                self._send(200, {"ok": True})
            elif url.path == "/api/run":
                ticks = max(1, min(int(body.get("ticks", 6)), 48))
                self._send(200, _start_run(self.state, slug, ticks))
            elif url.path == "/api/providers":
                self._send(200, _set_env(self.state, dict(body.get("values", {}))))
            elif url.path == "/api/chat":
                message = str(body.get("message", "")).strip()
                if not message:
                    self._send(400, {"ok": False, "error": "empty message"})
                    return
                self._send(200, _chat(self.state, slug, message))
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            log.exception("POST %s failed", self.path)
            self._send(500, {"ok": False, "error": str(exc)})


def build_server(settings: Settings, host: str | None = None, port: int | None = None,
                 env_file: Path | None = None) -> ThreadingHTTPServer:
    state = UiState(settings, env_file or ROOT / ".env")
    handler = type("BoundHandler", (Handler,), {"state": state})
    return ThreadingHTTPServer((host or settings.ui_host, settings.ui_port if port is None else port), handler)


def serve(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    server = build_server(settings, host, port)
    bound = server.socket.getsockname()
    log.info("operator console on http://%s:%d (Ctrl+C to stop)", bound[0], bound[1])
    print(f"corparius console: http://{bound[0]}:{bound[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

"""The console's half of each use case. Rank 6.

Every function here is thin by construction, and that is the whole result of stage 6: the
services live in `app/` with explicit `(store, settings, …)` signatures, and what is left is
the part that is genuinely about *this* console — reading the in-process run out of `UiState`,
turning a refusal into a status code, starting a background thread.

The pattern that produced the split is worth keeping in view, because it repeated identically
nine times: **the barrier was never the logic, always a parameter.** `persist` took a
`UiState`; `chat` read `state.chats`; `overview` read `state.runs`. Three times, a console
object in a signature was the only reason a terminal could not call the function.

So the rule for anything added here: if it would work with a `Store` and a `Settings`, it
belongs in `app/`, not in this file. `tests/test_two_callers_agree.py` is the ratchet.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path

from .. import company as company_mod
from ..app import chat as app_chat
from ..app import companies as app_companies
from ..app import errors as app_errors
from ..app import mail as app_mail
from ..app import overview as app_overview
from ..app import publish as app_publish
from ..app import runs as app_runs
from ..app import settings as app_settings
from ..app import tasks as app_tasks
from ..config import cfg, settings_spec
from ..config.provider_table import OPENAI_COMPAT_PROVIDERS
from ..kernel import dotenv, i18n, paths
from ..orchestrator import Runtime
from ..providers import (
    claudecli,
    hardware,
    ollama_setup,
)
from ..providers.llm import connected_providers
from ..store import jobs as jobs_store
from ..tools.spec import SPEC
from . import contracts, state
from .contracts import RequestRefused
from .state import UiState

# `owner_token` is how the startup sweep decides whether a `running` job belongs to this process,
# and a client has nothing it could do with it. Publishing a value that gates a state transition
# is needless even on loopback, so the transport decides what crosses rather than the row deciding
# for it. `owner_pid` stays: a person can act on a PID.
_PRIVATE_JOB_FIELDS = ("owner_token",)


def publishable_job(job: dict) -> dict:
    """A job row as a client sees it.

    Here and not in `handlers.py` for the second time in this stage: that file's invariant is that
    every function in it is an endpoint, and `tests/test_route_table.py` caught this one on sight
    exactly as it caught `for_company`.
    """
    return {k: v for k, v in job.items() if k not in _PRIVATE_JOB_FIELDS}


def for_company(slug: str):
    """The company a request names, or the refusal to send instead.

    Here rather than in `handlers.py` because it is not an endpoint, and that file's invariant is
    that every function in it is one — `tests/test_route_table.py` holds both ends of the table
    against it, and the first version of this lived there and broke that guard on sight.

    `state.load_company` returns None for a slug the glob never produced, which is also the
    path-traversal guard: only names that exist are ever opened.
    """
    company = state.load_company(slug)
    if company is None:
        return None, contracts.refuse(
            404, contracts.UNKNOWN_COMPANY, f"no company here is called {slug!r}", slug=slug
        )
    return company, None


log = logging.getLogger("corparius.api.adapters")


# Everything the page may write: the provider panel's vars plus every row of the
# settings registry. Anything else is refused.
ALLOWED_VARS = settings_spec.WRITABLE


# Stored write-only: never returned by the API, only a "configured" boolean.
_SECRET_VARS = settings_spec.SECRETS


_CHAT_LIMIT = 30  # turns kept per company, in-process only


# Completed tasks sent to the console. They accumulate for the life of a company
# and this payload is polled every few seconds; the store keeps all of them.
DONE_KEPT = 60


def merge_env_file(path: Path, values: dict[str, str]) -> None:
    """`kernel.dotenv.merge`, with its refusal turned into a status code.

    The writer itself — and the reason a newline in a value is refused there rather than in
    each of its callers — is documented in `kernel/dotenv.py`. What is left here is the only
    part that is genuinely about HTTP: a caller that sent a bad value gets a 400 instead of
    a traceback. The CLI callers deliberately do not go through this; a `LineBreakRefused`
    reaching a terminal is more honest than a fabricated HTTP status.
    """
    try:
        dotenv.merge(path, values)
    except dotenv.LineBreakRefused as exc:
        raise RequestRefused(400, str(exc)) from exc


def overview(ui: UiState, slug: str) -> tuple[int, dict]:
    """`app.overview.build`, holding the console's own in-flight run.

    The service takes the run as a parameter — that one line, `ui.runs`, was the whole reason
    a terminal could not have this, exactly as `ui.chats` was for the chat.

    **A company that is not here is a 404**, and it was a 200 until the v1 resources were written
    beside it. `state.load_company` returns None for an unknown slug, `build` then read
    `company_cfg = {}`, and the answer was a complete payload describing a company at tick 0 with
    nothing done — so "there is no such company" and "that company has done nothing" were the
    same response. Measured while smoking the v1 routes on the real machine:
    `/api/overview?company=nope` answered 200 and reported a phantom.

    `corparius status` has always refused it (`support.load_company` exits with a message), so
    the two callers of the same knowledge disagreed — which is the thing
    `tests/test_two_callers_agree.py` exists to catch and could not, because it compares which
    service each side reaches and both reach this one.

    The shape stays the legacy flat sentence; only the status changes. The page never sends an
    unknown slug — it offers the list it was given — except in the one case that matters: a
    company deleted in another tab, still being polled here. A banner saying it is gone is the
    truth; an empty dashboard is not.
    """
    company = state.load_company(slug)
    if company is None:
        return 404, {"ok": False, "error": f"unknown company '{slug}'"}
    return 200, app_overview.build(
        ui.store(),
        state.fresh_settings(),
        slug,
        company=company,
        run=run_view(ui, slug),
    )


def providers_payload() -> dict:
    s = state.fresh_settings()
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


def chat(ui: UiState, slug: str, message: str, lang: str = "en") -> dict:
    """`app.chat.once`, holding the console's own conversation history.

    The service takes the history as a parameter — that one line, `ui.chats`, was the whole
    reason a terminal could not have this. What is left here is owning the deque, which is a
    console concern: it lives in process memory and does not survive a restart, and pretending
    otherwise is schema 19's job rather than this function's.
    """
    return app_chat.once(
        ui.store(),
        state.fresh_settings(),
        slug,
        message,
        history=ui.chats.setdefault(slug, deque(maxlen=_CHAT_LIMIT)),
        lang=lang,
    )


def run_view(ui: UiState, slug: str) -> dict:
    """`app.runs.view`, plus the one thing only this process knows.

    The in-memory `Event` is the console's own click landing microseconds before the column it
    also sets. Everything else comes from the job row, which is why a restarted console reports
    `interrupted` instead of reporting nothing.
    """
    held = ui.runs.get(slug) or {}
    stop = held.get("stop")
    return app_runs.view(ui.store(), slug, stopping=bool(stop is not None and stop.is_set()))


def start_run(
    ui: UiState, slug: str, ticks: int, loop: bool = False, lang: str = "en", key: str = ""
) -> tuple[int, dict]:
    """Start a run, and record it where a restart cannot lose it.

    Three things changed when `jobs` arrived, and each removes a guess:

    **The guard is the store.** "A run is already in progress" used to be `ui.runs`, a dict in
    this process — so a run left behind by a crashed console was invisible to the next one and a
    second run would start on top of it. `running_job` is durable, and startup marks what this
    process does not own as `interrupted` before anything can ask.

    **`key` is `Idempotency-Key`.** A phone on 4G that retries this must not start two runs, so a
    repeated key returns the *same* job with `created: false` rather than a refusal the client
    would have to interpret.

    **The stop signal is both.** The event for this console's own button, the column for anybody
    else's — read together by the `should_stop` the orchestrator already polls at every tick.
    """
    company = state.load_company(slug)
    if company is None:
        return 404, {"ok": False, "error": f"unknown company '{slug}'"}
    store = ui.store()
    # The key is consulted **before** the already-running guard, and the order is the whole point.
    # The first version checked the guard first, so a phone retrying the request it had just made
    # was told "a run is already in progress" — by its own run. Exactly the situation the key
    # exists to make harmless, answered with the error it exists to prevent. Found by the test.
    if key:
        seen = store.job_for_key(key)
        if seen:
            return 200, {"ok": True, "job": seen["id"], "created": False, **run_view(ui, slug)}
    already = store.running_job(app_runs.KIND, slug)
    if already:
        return 409, {
            "ok": False,
            "error": "a run is already in progress",
            "job": already["id"],
        }
    started = store.start_job(
        app_runs.KIND,
        slug,
        idempotency_key=key,
        progress="starting",
        params={"ticks": int(ticks), "loop": bool(loop)},
    )
    job_id = started["id"]
    if not started["created"]:
        # Two requests carrying one key arrived close enough together to race past the read above.
        # The unique index is what actually decides, and this is the loser being told so.
        return 200, {"ok": True, "job": job_id, "created": False, **run_view(ui, slug)}
    stop = threading.Event()
    with ui.lock:
        ui.runs[slug] = {"job": job_id, "stop": stop}

    def _worker() -> None:
        try:
            runtime = Runtime(state.fresh_settings(), store)
            result = runtime.run(
                company,
                ticks=ticks,
                loop=loop,
                should_stop=lambda: stop.is_set() or store.cancel_requested(job_id),
            )
            ended = jobs_store.CANCELLED if store.cancel_requested(job_id) else jobs_store.DONE
            store.finish_job(job_id, ended, result)
        except Exception:  # surface, never swallow; detail to the log, not the operator
            log.exception("run failed for %s", slug)
            store.finish_job(
                job_id,
                jobs_store.FAILED,
                {
                    "error": i18n.pick(
                        lang,
                        "The run stopped on an unexpected error. See the server log for details.",
                        "Le run s'est arrêté sur une erreur inattendue. Voir le journal du serveur.",
                    )
                },
            )
        finally:
            with ui.lock:
                ui.runs.pop(slug, None)

    threading.Thread(target=_worker, daemon=True, name=f"corparius-run-{slug}").start()
    return 200, {"ok": True, "running": True, "loop": loop, "job": job_id, "created": True}


def stop_run(ui: UiState, slug: str) -> tuple[int, dict]:
    """Ask the run to stop. It lands within a tick; the thread is never killed, so the company's
    clock and the action log stay consistent.

    The column is written first and it is the one that matters: a client that is not this process
    — a phone, another terminal — has no event to set, and this is what lets it stop a run it did
    not start. The event is then set as well, because for the console's own button a tick is
    long enough to feel like nothing happened.
    """
    store = ui.store()
    job = store.running_job(app_runs.KIND, slug)
    if job is None:
        return 404, {"ok": False, "error": "no run in progress"}
    store.request_cancel(job["id"])
    store.set_job_progress(job["id"], "stopping")
    held = ui.runs.get(slug) or {}
    stop = held.get("stop")
    if stop is not None:
        stop.set()
    return 200, {"ok": True, "stopping": True, "job": job["id"]}


_DEFAULT_AGENTS = company_mod.DEFAULT_AGENTS  # kept: the wizard's checkbox list


def create_company(ui: UiState, body: dict) -> dict:
    """`app.companies.create`, with its refusal turned into a payload.

    The wizard asks for two fields and fills the rest from the same validator the editor uses,
    so a company created here and one edited later can never disagree about what a company is.
    The service is what lets a terminal have that too — before this there was no way to create
    a company from one at all.
    """
    try:
        out = app_companies.create(
            ui.store(),
            name=str(body.get("name", "")),
            one_liner=str(body.get("one_liner", "")),
            product=str(body.get("product") or ""),
            segment=str(body.get("segment") or ""),
            template=str(body.get("template", "")),
            agents=dict(body.get("agents", {})),
            session_tokens=int(body.get("session_tokens", app_companies.DEFAULT_SESSION_TOKENS)),
            lang=str(body.get("lang", "")),
        )
    except app_errors.Refused as exc:
        return {"ok": False, "error": str(exc)}
    log.info("company created from the console: %s", out["slug"])
    return {
        "ok": True,
        "slug": out["slug"],
        "companies": state.companies(),
        "warnings": out["warnings"],
    }


def company_payload(slug: str) -> dict:
    cfg = state.load_company(slug)
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
        "tools": sorted(SPEC),
    }


def save_company(ui: UiState, slug: str, body: dict) -> dict:
    if slug not in state.companies():
        return {"ok": False, "error": f"unknown company '{slug}'"}
    incoming = dict(body or {})
    incoming["slug"] = slug  # the slug is the directory; renaming is a move, not an edit
    cfg, errors, warnings = company_mod.validate(incoming)
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    company_mod.dump(cfg, company_mod.path_for(slug))
    log.info("company edited from the console: %s", slug)
    return {**company_payload(slug), "warnings": warnings, "saved": True}


def delete_company(ui: UiState, slug: str, confirm: str, purge: bool) -> dict:
    """`app.companies.delete`, with its refusal turned into a payload.

    The trash half destroys nothing — the config is moved, so a mistake is a `mv` away from
    undone — which is what makes the same operation safe to offer from a terminal. The console
    adds the list of companies, because that is what its page redraws.
    """
    try:
        out = app_companies.delete(ui.store(), slug, confirm, purge)
    except app_errors.Refused as exc:
        return {"ok": False, "error": str(exc)}
    log.info("company moved to trash from the console: %s -> %s", slug, out["trashed"])
    return {"ok": True, "companies": state.companies(), **out}


def persist(ui: UiState, values: dict[str, str], unset: list[str] | None = None) -> dict:
    """`app.settings.persist`, with its refusal turned into a status code.

    The service takes `(store, env_file)` rather than a `UiState`, which is what makes it
    reachable from the command line — the console object was the only reason it was not. What
    is left here is the part that is genuinely about HTTP: a value with a newline in it comes
    back as a 400 instead of a traceback, exactly as `merge_env_file` does one layer down.
    """
    try:
        return app_settings.persist(ui.store(), ui.env_file, values, unset)
    except dotenv.LineBreakRefused as exc:
        raise RequestRefused(400, str(exc)) from exc


def set_env(ui: UiState, values: dict) -> dict:
    """The providers panel: toggles, routing tiers and provider keys."""
    clean: dict[str, str] = {}
    for key, value in values.items():
        if key not in ALLOWED_VARS:
            return {"ok": False, "error": f"variable '{key}' is not settable"}
        clean[key] = str(value).strip()
    meta = persist(ui, clean)
    return {**providers_payload(), **meta}


def edit_task(store, body: dict) -> tuple[int, dict]:
    """`app.tasks.edit`, with its refusal turned into a status code.

    The service takes one keyword per field instead of this body dict, which is what let the
    command line reach it — a dict shaped like a request body *is* a request. What is left here
    is unpacking and the status code, which is the only part that is about HTTP.
    """
    try:
        changed = app_tasks.edit(
            store,
            body.get("id"),
            title=body.get("title"),
            priority=body.get("priority"),
            target=body.get("target"),
            tool=body.get("tool"),
            decision=body.get("decision"),
            note=str(body.get("note", "via console")),
        )
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 200, {"ok": True, **changed}


def deploy(ui: UiState, slug: str) -> tuple[int, dict]:
    """`app.publish.publish`, with its refusal turned into a status code.

    The service resolves the folder — the company's own site wins over the generated one — and
    that is the half the command line never had. What is left here is the 404 and the envelope.
    """
    try:
        out = app_publish.publish(
            slug, state.fresh_settings().data_path, state.load_company(slug), ui.store()
        )
    except app_errors.Refused as exc:
        return 404, {"ok": False, "error": str(exc)}
    # The envelope succeeded; whether anything published is the payload's news.
    return 200, {"ok": True, **{k: v for k, v in out.items() if k != "folder"}}


def golive_status(slug: str) -> dict:
    """The three things between a mock company and one that can take money: a
    checkout link, a mail account, and a public host. Reported as booleans plus
    the live URL, so one card can guide the operator from A to Z."""
    company = state.load_company(slug) or {}
    offer = company.get("offer", {}) or {}
    pay = (
        str(offer.get("payment_link") or "").strip()
        or cfg.get("CORP_STRIPE_PAYMENT_LINK", "").strip()
    )
    published_url = ""
    marker = paths.site_dir(state.fresh_settings().data_path, slug) / ".published"
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


def ollama_pull(ui: UiState, models: list) -> dict:
    """Pull the named models (or every missing one) in the background. A pull is
    gigabytes, so it runs in a thread and reports progress through /api/ollama,
    the same shape as a run."""
    models = [str(m).strip() for m in models if str(m).strip()] or ollama_setup.status()["missing"]
    if not models:
        return {"ok": True, "detail": "nothing to pull"}
    with ui.lock:
        if ui.pulls.get("running"):
            return {"ok": False, "error": "a pull is already in progress"}
        ui.pulls = {"running": True, "progress": "", "done": [], "failed": []}

    def _worker() -> None:
        for model in models:

            def note(line):
                ui.pulls["progress"] = line

            res = ollama_setup.pull(model, on_line=note)
            (ui.pulls["done"] if res["ok"] else ui.pulls["failed"]).append(model)
        ui.pulls["running"] = False
        ui.pulls["progress"] = "done"

    threading.Thread(target=_worker, daemon=True, name="corparius-ollama-pull").start()
    return {"ok": True, "pulling": models}


def claude_setup(ui: UiState, all_tiers: bool = False) -> dict:
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
    # One probe, reused. providers_payload() below used to run a second one,
    # and two four-second connect timeouts on a machine with no Ollama exceeded
    # the console client's own timeout.
    local_trivial, _why = hardware.recommended_local(ui.store(), state.fresh_settings())
    from ..providers import modelinfo, preflight

    applied = claudecli.plan(
        connected_providers(),
        local_trivial,
        all_tiers=all_tiers,
        proven=preflight.proven_map(ui.store()),
        catalogue=modelinfo.cached(ui.store()),
        scores=modelinfo.operator_scores(),
    )
    persist(ui, applied)
    payload = providers_payload()
    return {**payload, "check": result, "applied": applied}


def oops(lang: str = "en") -> str:
    """The message for an unexpected error. The full traceback goes to the server
    log; the operator gets a sentence, not Python internals."""
    return i18n.pick(
        lang,
        "Something went wrong on the console. The details are in the server log.",
        "Un problème est survenu dans la console. Les détails sont dans le journal du serveur.",
    )


def settings_payload() -> dict:
    return {
        "ok": True,
        "groups": settings_spec.GROUPS,
        "fields": [settings_spec.describe(f.key) for f in settings_spec.SPEC],
        "warning": {"en": settings_spec.WARN_EN, "fr": settings_spec.WARN_FR},
        "mail_presets": settings_spec.MAIL_PRESETS,
        "mail_steps": app_mail.steps(),
    }


def set_settings(ui: UiState, values: dict, unset: list) -> dict:
    """Validate against the registry, then persist. An empty value clears the
    setting rather than storing an empty string, so the layer below shows
    through again."""
    clean, drop, errors = app_settings.validate(values, unset)
    if errors:
        return {"ok": False, "error": "; ".join(errors)}
    meta = persist(ui, clean, drop)
    return {**settings_payload(), **meta}


def theme_file() -> Path:
    """Where the console's colour choice lives: a small JSON in the data dir,
    deliberately separate from the settings table (this is per-instance UI state,
    not app configuration). Persisting it here is what makes the theme follow the
    operator across browsers and devices on the same instance."""
    return Path(state.fresh_settings().data_path) / "ui_theme.json"


def theme_get() -> dict:
    try:
        data = json.loads(theme_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def theme_set(body: dict) -> dict:
    """Merge validated fields (mode, hue, chroma) into the stored theme. A null or
    empty value clears a field (back to the code default)."""
    current = theme_get()
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
        path = theme_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current), encoding="utf-8")
    except OSError:
        pass
    return current


def plugins_action(body: dict) -> dict:
    """Enable/disable/remove an installed plugin, or install a VERIFIED one from
    the curated registry. Installing an unverified plugin is deliberately not
    reachable from the console — that path is CLI-only, behind the opt-in."""
    from .. import plugins

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

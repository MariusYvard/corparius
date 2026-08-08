"""One function per endpoint. Rank 6.

Each returns `(status, payload)` or `(status, payload, content_type)`. They take a `Ctx` and
nothing else, which is what makes every one of them callable without an HTTP round trip — and
what a good half of the test suite does.

By layer, not by page. A `handlers/settings.py` and a `handlers/site.py` would recreate the
god-file once per tab; what keeps this file readable instead is that the thinking is in `app/`
and the endpoints are adapters. **Both ends are held**: every `Route.handler` is a function of
this module and every function of this module is in the table (`tests/test_route_table.py`) —
a handler that fell out of the table used to be invisible.

The leading underscore these carried is gone. It existed because everything lived in one
2 468-line file, where `_route_meta` distinguished a handler from its neighbours; in a module
whose every function is a handler it was the module's own name, repeated 57 times.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from .. import (
    backup,
    documents,
    sitegen,
)
from .. import company as company_mod
from ..app import errors as app_errors
from ..app import mail as app_mail
from ..app import meta as app_meta
from ..app import skills as app_skills
from ..config import cfg, permissions
from ..config.provider_table import OPENAI_COMPAT_PROVIDERS, split_target
from ..doctor import run_checks
from ..kernel import paths
from ..providers import (
    claudecli,
    hardware,
    ollama_setup,
    provider_check,
)
from ..providers.integrations import stripe_check, stripe_payments
from ..providers.llm import connected_providers
from ..tools.spec import SPEC
from . import adapters, state

log = logging.getLogger("corparius.api.handlers")


PAGE = paths.page_file()


def page(ctx):
    return 200, PAGE.read_bytes(), "text/html"


def companies_get(ctx):
    return 200, {"ok": True, "companies": state.companies(), "templates": company_mod.TEMPLATES}


def overview(ctx):
    return 200, adapters.overview(ctx.state, ctx.slug)


def providers_get(ctx):
    return 200, adapters.providers_payload()


def settings_get(ctx):
    return 200, adapters.settings_payload()


def company_get(ctx):
    result = adapters.company_payload(ctx.slug)
    return (200 if result["ok"] else 404), result


def meta(ctx):
    """What this core is and what it can do — the first thing a second client asks.

    Public, like `/api/session`, and for the same reason: a client has to be able to learn what
    it is talking to before it can authenticate to it. It names no secret, no company and no
    setting value; `capabilities` is a set of booleans about configuration.

    Versioned in the path from the start. The plan's rule is that every new route is `/api/v1/`
    and the unprefixed ones are a declared legacy set — `tests/test_api_version.py` holds it,
    so the next route added outside v1 has to say why.
    """
    return 200, {"ok": True, **app_meta.describe(state.fresh_settings(), ctx.state.store())}


def session(ctx):
    # Tells the page whether it must send X-Corp-Token. It never serves the
    # token itself.
    return 200, {"ok": True, "token_required": bool(cfg.get("CORP_UI_TOKEN", "").strip())}


def ollama_get(ctx):
    result = ollama_setup.status(lang=ctx.lang)
    pulls = ctx.state.pulls
    if pulls.get("running"):
        result = {**result, "detail": pulls.get("progress") or "pulling...", "pulling": True}
    # The cached measurement only — this endpoint is polled while a pull runs.
    settings = state.fresh_settings()
    prof = hardware.profile(ctx.store(), max_age_days=settings.bench_max_age_days)
    choice, why = hardware.recommended_local(ctx.store(), settings, result.get("installed"))
    return 200, {
        "ok": True,
        "result": {**result, "machine": prof, "local_model": choice, "local_reason": why},
    }


def ollama_bench(ctx):
    """Measure, on a button press. The one place in the console that may: it
    costs a real generation — 93 seconds to load the configured model on the
    machine this was written for — so it can never sit on a polled path."""
    settings = state.fresh_settings()
    models = hardware.installed_models()
    if not models:
        return 200, {"ok": True, "result": {"ok": False, "detail": "no local model to measure"}}
    want = hardware.best_local_model(models, prefer=split_target(settings.trivial_model)[1])
    spec = hardware.specs()
    measured = hardware.measure(want or models[0]["name"])
    if measured["ok"]:
        hardware.profile_save(ctx.store(), spec, measured)
    return 200, {"ok": True, "result": measured}


def drafts_get(ctx):
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


def drafts_post(ctx):
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


def documents_get(ctx):
    """What the company has on file, and what of it an agent actually reads.

    The folder shipped, the agents write into it, and nothing in the console
    showed either half. So the operator could not read a brief their own design
    agent had written, and could not see that ten of their twelve documents were
    sitting past the prompt budget, never reaching a turn.

    Deliberately off the 5s poll — this opens and extracts every file it lists,
    and a PDF regex on a polled path is the same mistake as a network probe on
    one. The page loads it on arrival, on a company change, when a run ends, and
    when somebody presses the button.
    """
    # `slug in companies()` is the path-traversal guard, as everywhere else:
    # `documents.folder` builds a path out of this name.
    if ctx.slug not in state.companies():
        return 404, {"ok": False, "error": "no such company"}
    return 200, {"ok": True, **documents.inventory(ctx.slug)}


def documents_post(ctx):
    """Store one file the operator dropped on the console.

    One file per request, deliberately. A batch would need a body ceiling sized
    for the worst case it might ever carry, would collapse ten outcomes into one
    answer, and would make per-file progress on the page a thing the page made up.

    A refused file is not a failed request: `ok` qualifies the request, and asking
    to store a .zip is a perfectly well-formed thing to ask. The answer is
    `stored: False` with the reason, and the operator learns which file and why.
    """
    if ctx.slug not in state.companies():
        return 404, {"ok": False, "error": "no such company"}
    try:
        # validate=True, so a body that is not base64 says so here rather than
        # writing whatever survived a lenient decode into the operator's folder.
        data = base64.b64decode(str(ctx.body.get("data", "")), validate=True)
    except ValueError:  # binascii.Error subclasses it
        return 400, {"ok": False, "error": "the file did not arrive as valid base64"}
    name = str(ctx.body.get("name", ""))
    try:
        path, replaced = documents.save(ctx.slug, name, data)
    except documents.Refused as refused:
        return 200, {
            "ok": True,
            "stored": False,
            "name": name,
            "reason": refused.reason,
            "detail": refused.detail,
            **documents.inventory(ctx.slug),
        }
    # The refreshed inventory rides back with the result, so the card the operator
    # is looking at is the folder as it now stands rather than as it was.
    return 200, {
        "ok": True,
        "stored": True,
        "replaced": replaced,
        "name": path.name,
        **documents.inventory(ctx.slug),
    }


def document_text(ctx):
    """One document's whole extracted text, with no prompt budget applied.

    The card reused the text an agent gets, which is capped at
    `documents.MAX_CHARS` so a thirty-page deck cannot swallow a turn. Honest — the
    badge says "first 4000 of 12000" — and still the wrong answer for a person
    rereading their own brief, who had to go open the file. The reading surface and
    the prompt budget are different questions.

    A GET, because it reads; and off the 5s poll, because it extracts a file.
    """
    if ctx.slug not in state.companies():
        return 404, {"ok": False, "error": "no such company"}
    doc = documents.full_text(ctx.slug, str(ctx.query.get("path", "")))
    if doc is None:
        return 404, {"ok": False, "error": "no such document"}
    return 200, {"ok": True, "path": doc.label, **doc.as_dict(), "text": doc.text}


def documents_delete(ctx):
    """Take one document out of the folder.

    A drop zone with no way back is a folder that only grows, and an operator who
    dropped the wrong quarter's price list had to go find the directory by hand.
    Moved aside rather than erased, like a deleted company: the answer says where
    it went, so a misread badge is recoverable.

    No typed confirmation, unlike deleting a company. That gate exists because a
    company is the whole thing; a document is one file that is still on disk
    afterwards, and friction on a routine action buys nothing here.
    """
    if ctx.slug not in state.companies():
        return 404, {"ok": False, "error": "no such company"}
    try:
        moved = documents.remove(ctx.slug, str(ctx.body.get("path", "")))
    except documents.Refused as refused:
        return 200, {
            "ok": True,
            "removed": False,
            "reason": refused.reason,
            "detail": refused.detail,
            **documents.inventory(ctx.slug),
        }
    return 200, {
        "ok": True,
        "removed": True,
        "trashed": moved.name,
        **documents.inventory(ctx.slug),
    }


def site_get(ctx):
    owned = paths.owned_site(ctx.slug)
    site = (
        (owned / "index.html")
        if owned
        else paths.site_index(state.fresh_settings().data_path, ctx.slug)
    )
    return 200, {
        "ok": True,
        "built": site.is_file(),
        "mtime": site.stat().st_mtime if site.is_file() else None,
        # Which site the console is showing, so the preview cannot silently be a
        # different page from the one that gets published.
        "owned": owned is not None,
        "pages": sorted(p.name for p in owned.glob("*.html")) if owned else [],
    }


# What the preview will serve, and nothing else. A site is HTML, styles, scripts,
# images and fonts; anything not on this list is a source file or a secret that
# happened to be in the folder, and the preview is not a general file server.
SITE_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
}


def site_serve(ctx):
    """The preview, for a real site rather than a single page.

    It used to serve `index.html` and nothing else, which was fine while the site
    *was* one generated page. For a company that ships its own — Vigil's four pages
    with a stylesheet, a script, a blog folder — every `/assets/style.css`,
    `/tech.html` and `/blog/` came back 404, so the preview rendered the operator's
    real copy in Times New Roman with blue underlined links. They sent a screenshot
    of it and reasonably read it as the site being broken.

    Two guards, both before any path is built: the slug must be a known company, and
    the resolved file must still be inside the site folder. Only the extensions in
    SITE_TYPES are served — the preview is not a general file server, and a company
    folder holds sources and configuration next to the site.
    """
    parts = ctx.path.split("/", 3)  # ["", "site", slug, rest]
    slug = parts[2] if len(parts) > 2 else ""
    rest = parts[3] if len(parts) > 3 else ""
    # `slug in companies()` is the path-traversal guard on the slug, as everywhere
    # else, and it runs before any path is built from it.
    if slug not in state.companies():
        return 404, {"ok": False, "error": "site not built yet"}
    owned = paths.owned_site(slug)
    root = owned if owned else paths.site_dir(state.fresh_settings().data_path, slug)
    rest = unquote(rest.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
    if not rest or rest.endswith("/"):
        rest += "index.html"
    try:
        # resolve() then a containment check: this is what stops `..%2f..%2f.env`,
        # and it is checked on the resolved path rather than on the text of the URL.
        target = (root / rest).resolve()
        target.relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return 404, {"ok": False, "error": "not part of this site"}
    kind = SITE_TYPES.get(target.suffix.lower())
    if kind is None:
        return 404, {"ok": False, "error": f"{target.suffix or 'that file'} is not served"}
    if not target.is_file():
        return 404, {"ok": False, "error": "site not built yet"}
    return 200, target.read_bytes(), kind


def payments_get(ctx):
    return 200, {"ok": True, **stripe_payments()}


def doctor(ctx):
    # Lends the console's own connection. Seven checks used to open one each and
    # close only three, so answering this poll opened seven and leaked four — and
    # on a slow runner it pushed this endpoint past the page's own timeout.
    return 200, {"ok": True, "checks": run_checks(state.fresh_settings(), ctx.store())}


def update(ctx):
    # Off unless CORP_UPDATE_CHECK is on; when off this makes no network call.
    # See corparius/update_check.py.
    from .. import selfupdate, update_check

    return 200, {"ok": True, **update_check.check(), "can_apply": not selfupdate.why_not()}


def update_apply(ctx):
    """Download the newest release and swap the binary, on a button press.

    A POST, never the polled GET beside it: this one downloads tens of
    megabytes and then replaces the program. The route exists on every build so
    the refusal is explainable — from source or Docker it says what to do
    instead rather than pretending the button is missing.
    """
    from .. import selfupdate, update_check

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


def plugins_get(ctx):
    from .. import plugins, skills

    s = state.fresh_settings()
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
                "unknown_tools": [t for t in sk.allowed_tools if t not in SPEC],
                "chars": len(sk.instructions),
                "unscoped": sk.unscoped,
                # Whether the author said so. An always-on guardrail is still
                # reported — it is not free — but a warning badge on a choice
                # somebody made deliberately is a warning they learn to ignore.
                "always": sk.always,
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
        "tool_names": sorted(SPEC),
    }


def skill_scope(ctx):
    """`app.skills.scope`, with its refusal turned into a status code.

    The one write the skills panel does — and until the service existed, the only way to make
    it at all. An unscoped skill rides every prompt of every turn, and `corparius skills list`
    reported that cost from a terminal while offering nothing to do about it.
    """
    try:
        out = app_skills.scope(
            ctx.slug or "",
            str(ctx.body.get("name", "")),
            list(ctx.body.get("tools") or []),
            state.fresh_settings(),
        )
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    log.info("skill %s scoped to %s", out["name"], ", ".join(out["tools"]))
    return 200, {"ok": True, "name": out["name"], "tools": out["tools"]}


def theme_get(ctx):
    return 200, {"ok": True, **adapters.theme_get()}


def chat_get(ctx):
    return 200, {"ok": True, "history": list(ctx.state.chats.get(ctx.slug, []))}


def companies_post(ctx):
    return 200, adapters.create_company(ctx.state, ctx.body)


def approvals_post(ctx):
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
        tool = SPEC.get(approval["tool"])
        engine = permissions.PermissionEngine.from_settings(
            state.fresh_settings(), state.load_company(slug) or {}, store
        )
        if tool and engine.evaluate(tool, slug).rule != "hitl":
            store.add_rule(slug, approval["tool"], scope, "granted from the console")
            remembered = scope
    return (200 if done else 404), {
        "ok": done,
        "remembered": remembered,
        "error": None if done else "approval not found",
    }


def inbox_post(ctx):
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


def memory_post(ctx):
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


def rules_post(ctx):
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


def tasks_post(ctx):
    return adapters.edit_task(ctx.store(), ctx.body)


def site_post(ctx):
    company = state.load_company(ctx.slug)
    if company is None:
        return 404, {"ok": False, "error": f"unknown company '{ctx.slug}'"}
    out_dir = paths.site_dir(state.fresh_settings().data_path, ctx.slug)
    headline = str(ctx.body.get("headline", "")).strip()
    sitegen.build_site(company, str(out_dir), headline=headline or None, store=ctx.state.store())
    return 200, {"ok": True, "built": True}


def deploy_post(ctx):
    return adapters.deploy(ctx.state, ctx.slug)


def backup_post(ctx):
    path = backup.make_backup(state.fresh_settings().data_path)
    return 200, {
        "ok": True,
        "name": path.name,
        "size": path.stat().st_size,
        "warning": {"en": backup.WARNING_EN, "fr": backup.WARNING_FR},
    }


def run_stop(ctx):
    return 200, adapters.stop_run(ctx.state, ctx.slug)


def run_post(ctx):
    ticks = max(1, min(int(ctx.body.get("ticks", 6)), 48))
    return 200, adapters.start_run(
        ctx.state, ctx.slug, ticks, loop=bool(ctx.body.get("loop")), lang=ctx.lang
    )


def providers_post(ctx):
    return 200, adapters.set_env(ctx.state, dict(ctx.body.get("values", {})))


def golive(ctx):
    return 200, adapters.golive_status(ctx.slug)


def tiers_recommend(ctx):
    # One click to a coherent routing over the free providers actually connected:
    # flip mock off and cloud on, then fill every tier so none is left pointing at
    # an unconfigured provider (the trap the defaults leave after a single key).
    from ..providers.routing import recommended_routing

    local_trivial, _why = hardware.recommended_local(ctx.store(), state.fresh_settings())
    # What a preflight actually proved, so "recommended" never writes a tier
    # this key cannot call. Empty until someone runs one, and then this behaves
    # exactly as it did before.
    from ..providers import modelinfo, preflight

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
    result = adapters.set_env(
        ctx.state, {"CORP_LLM_MOCK": "false", "CORP_CLOUD_ENABLED": "true", **routing}
    )
    return (200 if result.get("ok") else 400), {**result, "routing": routing}


def provider_models(ctx):
    # The models a provider advertises, so a tier can be filled from a list rather
    # than a remembered string. A network failure is reported, never a 500.
    from ..providers import preflight
    from ..providers.llm import list_models

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


def settings_post(ctx):
    result = adapters.set_settings(
        ctx.state, dict(ctx.body.get("values", {})), list(ctx.body.get("unset", []))
    )
    return (200 if result.get("ok") else 400), result


def plugins_post(ctx):
    result = adapters.plugins_action(ctx.body)
    return (200 if result.get("ok") else 400), result


def theme_post(ctx):
    return 200, {"ok": True, **adapters.theme_set(ctx.body)}


def test_mail(ctx):
    # One button, both directions. A real send and a real read: setting a mail
    # account and hoping is the friction, and this is the answer to "did it work?".
    return 200, {"ok": True, "result": app_mail.check(str(ctx.body.get("to", "")), ctx.lang)}


def test_payments(ctx):
    return 200, {"ok": True, "result": stripe_check(lang=ctx.lang)}


def test_claude(ctx):
    return 200, {"ok": True, "result": claudecli.check(lang=ctx.lang)}


def claude_install(ctx):
    """Install the CLI, on a button press.

    It puts a global npm package on the operator's machine, so it never happens
    as a side effect of a status check — only here, and only from this console,
    which is bound to localhost behind a token.
    """
    if claudecli.installed():
        return 200, {"ok": True, "result": {"ok": True, "detail": "already installed"}}
    return 200, {"ok": True, "result": claudecli.install()}


def claude_setup(ctx):
    result = adapters.claude_setup(ctx.state, all_tiers=bool(ctx.body.get("all_tiers")))
    return (200 if result.get("ok") else 400), result


def test_provider(ctx):
    return 200, {
        "ok": True,
        "result": provider_check.check(str(ctx.body.get("name", "")), lang=ctx.lang),
    }


def preflight(ctx):
    """Call every configured model once, for eight tokens, and remember it.

    A POST, never a GET on a polled path: each probe is a real generation on the
    operator's own account. The doctor reads what this leaves behind and never
    measures — the same split as the hardware bench.
    """
    from ..providers import preflight

    s = state.fresh_settings()
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


def sweep_get(ctx):
    """Progress of a running sweep, and what is known when none is running.

    A GET, polled by the page — so it reads state and calls nobody. The probing
    happens in the worker thread that the POST started.
    """
    from ..providers import preflight

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


def sweep_post(ctx):
    """Start — or price, or stop — a sweep of every configured provider.

    `{"estimate": true}` returns the number of calls it would make without
    making any. That is deliberate: NVIDIA alone advertises 102 models, and an
    operator pressing "check everything" is spending their own money and their
    own rate limits. They get the number first.
    """
    from ..providers import preflight

    s = state.fresh_settings()
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


def ollama_pull(ctx):
    return 200, adapters.ollama_pull(ctx.state, list(ctx.body.get("models", [])))


def company_post(ctx):
    result = adapters.save_company(ctx.state, ctx.slug, dict(ctx.body.get("config", {})))
    return (200 if result.get("ok") else 400), result


def company_delete(ctx):
    result = adapters.delete_company(
        ctx.state, ctx.slug, str(ctx.body.get("confirm", "")), bool(ctx.body.get("purge_store"))
    )
    return (200 if result.get("ok") else 400), result


def chat_post(ctx):
    message = str(ctx.body.get("message", "")).strip()
    if not message:
        return 400, {"ok": False, "error": "empty message"}
    return 200, adapters.chat(ctx.state, ctx.slug, message, ctx.lang)

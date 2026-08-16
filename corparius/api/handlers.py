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
from ..app import approvals as app_approvals
from ..app import drafts as app_drafts
from ..app import errors as app_errors
from ..app import inbox as app_inbox
from ..app import mail as app_mail
from ..app import memory as app_memory
from ..app import meta as app_meta
from ..app import overview as app_overview
from ..app import setup as app_setup
from ..app import skills as app_skills
from ..app import tasks as app_tasks
from ..config import cfg
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
from ..store import chat as chat_store
from . import adapters, contracts, state

log = logging.getLogger("corparius.api.handlers")


PAGE = paths.page_file()


def page(ctx):
    """The console, and from this commit that means the built one.

    The plan put the new console behind a flag "until the new bundle passes the i18n key-set
    equality test". It passes, all seven tabs are rebuilt, and so the flag's job is finished: `/`
    serves the shell from `corparius/api/static/`, which is what an operator gets by double-clicking
    `start-windows.bat` and typing nothing.

    **The fallback is not a flag, it is a fact about the checkout.** `static/` exists only after
    `npm run build`, so a source tree that has never run it — and a wheel built without the CI step
    — has no shell to serve. There, `/` keeps serving the single-file page it always did. That is
    the one arrangement where neither state is a broken console: built means new, unbuilt means old,
    and nothing has to be configured for either.

    The old page stays reachable at `/legacy` for as long as it ships. A path rather than an
    environment variable on purpose: an operator who hits a bug in the new console needs somewhere
    to click, not something to set and a restart to do it.
    """
    if paths.console_built():
        return 200, (paths.console_dir() / "index.html").read_bytes(), "text/html"
    return 200, PAGE.read_bytes(), "text/html"


def legacy_page(ctx):
    """The single-file console, unconditionally — the way back when the new one misbehaves.

    Its assets are not a concern the way the new shell's are: `webui.html` is 3 617 lines of HTML,
    CSS and JS in one file with no external reference, which is exactly why it can be served from
    any path with no build and no base. Every request it makes is a root-relative `/api/...`.
    """
    return 200, PAGE.read_bytes(), "text/html"


def companies_get(ctx):
    return 200, {"ok": True, "companies": state.companies(), "templates": company_mod.TEMPLATES}


def overview(ctx):
    return adapters.overview(ctx.state, ctx.slug)


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


# --- the v1 resources -----------------------------------------------------------
#
# `/api/overview` is 48 530 bytes on the real company and the page polls it every five seconds:
# 34 MB an hour, per client. Measured key by key, three lists are 94% of it, so the split is
# those three out and everything else in `summary` — 2 859 bytes, a 17× reduction for the one a
# client should actually poll. The parts are in `app/overview.py`; these four are the transport.
#
# All four are v1, so all four answer a refusal in the envelope and all four carry an `ETag`.
# What that buys is bandwidth, not work: the payload is still built before it is hashed. Saying
# so here because "a client at rest pays nothing" would be the easy overclaim, and the query is
# not free — narrowing what a client polls is what makes the query small.


def v1_summary(ctx):
    """The small one: the clock, the flow, what needs a person, and the run in flight.

    Including `approvals` and `inbox`, which the plan named as separate resources and which
    measure 613 bytes together — and which are the two things an operator must not have to make
    a second request to see.
    """
    company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {
        "ok": True,
        **app_overview.summary(
            ctx.store(),
            state.fresh_settings(),
            ctx.slug,
            company=company,
            run=adapters.run_view(ctx.state, ctx.slug),
        ),
    }


def v1_tasks(ctx):
    """21 KB of the 48, and the part that changes on every tick."""
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {"ok": True, **app_overview.tasks(ctx.store(), ctx.slug)}


def v1_memory(ctx):
    """17.7 KB that changes almost never, which is what makes the ETag worth having here."""
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {"ok": True, **app_overview.memory(ctx.store(), state.fresh_settings(), ctx.slug)}


def v1_activity(ctx):
    """The last 25 actions. A log: a client that has seen them has seen them."""
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {"ok": True, **app_overview.activity(ctx.store(), ctx.slug)}


def v1_companies(ctx):
    """Which companies exist here. The first thing a client asks after `meta`.

    Public like `meta` is not: a slug is a name the operator chose and it is theirs. Not slug-scoped
    either, obviously — it is the resource you read *to learn* the slugs.
    """
    return 200, {"ok": True, "companies": state.companies()}


def v1_companies_post(ctx):
    """Create one. The other verb on the resource above, and it was missing.

    Measured from the console: the Svelte header rendered a `<select>` of existing slugs and nothing
    else, so **there was no way to create a company from the new console at all** — the operator had
    to use the terminal or the old page. The service and the handler both existed (`companies_post`
    on the legacy path), so this was one line of route table and a header button away the whole time,
    which is exactly the shape this codebase keeps finding: reachable, and never reached.

    Not slug-scoped, for the obvious reason that the slug is what it returns."""
    result = adapters.create_company(ctx.state, ctx.body)
    return (200 if result.get("ok") else 400), result


def v1_approvals_post(ctx):
    """Decide an approval, and finish the job.

    One call into `app_approvals.decide`, which is the service the console, the terminal and an MCP
    host now share — and the reason it exists is that all three used to do something different, the
    console being the one that never released the work parked on the approval.

    `remember` is a scope (`run` or `always`) rather than a boolean, and a refusal to grant it is
    reported in `gated`: a client that offered "and stop asking" has to be able to say the answer
    was no, because the company names that tool in `hitl_tools` and a standing rule would overrule
    the file the operator wrote it in.
    """
    approval_id = str(ctx.body.get("id", "")).strip()
    if not approval_id:
        return contracts.refuse(400, contracts.INVALID, "an approval id is required", field="id")
    store = ctx.store()
    owner = str((store.get_approval(approval_id) or {}).get("company", ""))
    try:
        done = app_approvals.decide(
            store,
            state.fresh_settings(),
            approval_id,
            str(ctx.body.get("decision", "")),
            note=str(ctx.body.get("note", "")),
            remember=str(ctx.body.get("remember", "")),
            company=state.load_company(owner),
        )
    except app_errors.Refused as exc:
        return contracts.refuse(400, contracts.INVALID, str(exc), field="decision")
    if not done["found"]:
        return contracts.refuse(404, contracts.NOT_FOUND, "no such approval", id=approval_id)
    return 200, {"ok": True, **done}


def v1_inbox_post(ctx):
    """Answer a question, or dismiss a notice.

    First responder wins, and the refusal is `conflict` rather than `not_found`: a second answer to a
    decided item is not a missing item, it is one somebody else has already dealt with — and the
    waiting work has moved on. A client told `conflict` refreshes; one told `not_found` would think
    its list was stale in a different way.
    """
    item = str(ctx.body.get("id", "")).strip()
    if not item:
        return contracts.refuse(400, contracts.INVALID, "an inbox id is required", field="id")
    done = app_inbox.answer(ctx.store(), item, str(ctx.body.get("answer", "")), ctx.slug)
    if not done["answered"]:
        return contracts.refuse(
            409, contracts.CONFLICT, "already answered, or no such item", id=item
        )
    return 200, {"ok": True, **done}


def v1_tasks_post(ctx):
    """Edit one task, decide one proposal, or both at once.

    Straight into `app_tasks.edit`, which is the service the console and `corparius task` share —
    and the pair that found the first live divergence of this restructuring: the console validated
    the agent and the tool and called `executable_fields` on approval, and `cmd_task` called
    `store.update_task` directly with none of it. Approving from a terminal left the task with no
    tool, so it closed "done (no tool mapped)" having done nothing and the agent proposed it again.
    Measured on one company: 24 tasks for a role, 22 of them like that.

    `Refused` is a sentence for a person and `invalid` is the word a client switches on. The field
    is not named here because the service refuses across six of them and knowing which is its
    business — `detail.message` carries the sentence and that is honest, where guessing `field`
    would be a machine-readable lie.
    """
    try:
        changed = app_tasks.edit(
            ctx.store(),
            ctx.body.get("id"),
            title=ctx.body.get("title"),
            priority=ctx.body.get("priority"),
            target=ctx.body.get("target"),
            tool=ctx.body.get("tool"),
            decision=ctx.body.get("decision"),
            note=str(ctx.body.get("note", "via console")),
        )
    except app_errors.Refused as exc:
        return contracts.refuse(400, contracts.INVALID, str(exc))
    return 200, {"ok": True, **changed}


def v1_rules_post(ctx):
    """Revoke a standing rule.

    Granting one goes through the approval it came from — `POST /api/v1/approvals` with a
    `remember` scope — because a rule that appeared without an approval behind it would have no
    audit trail. Revoking has to stand alone, or a rule granted by mistake could only be undone by
    opening the database.

    One store call, and deliberately **not** a service: `corparius rules --revoke` makes the same
    call and there is no second thing that belongs with it. Nothing is parked on a standing rule —
    revoking means the tool asks again next time — so the shape that produced the approvals
    divergence (two calls, one caller forgetting the second) cannot arise here. Stated rather than
    left implicit, so the next reader knows it was checked and not overlooked.
    """
    tool = str(ctx.body.get("tool", "")).strip()
    if not tool:
        return contracts.refuse(400, contracts.INVALID, "a tool name is required", field="tool")
    if not ctx.store().drop_rule(ctx.slug, tool):
        return contracts.refuse(
            404, contracts.NOT_FOUND, "no standing rule for that tool", tool=tool
        )
    return 200, {"ok": True, "tool": tool, "rules": ctx.store().list_rules(ctx.slug)}


def v1_memory_post(ctx):
    """Pin one fact, unpin it, or forget it.

    The operator owns their company's memory the way they own its secrets: a wrong thing an agent
    wrote down has to be removable without opening the database. Pinning is the other half —
    `curator` archives a fact that has gone 90 days unused, and a pin is how an operator says this
    one stays regardless.
    """
    try:
        done = app_memory.decide(ctx.store(), ctx.body.get("id"), str(ctx.body.get("action", "")))
    except app_errors.Refused as exc:
        field = "id" if "id" in str(exc) else "action"
        return contracts.refuse(400, contracts.INVALID, str(exc), field=field)
    if not done["found"]:
        return contracts.refuse(404, contracts.NOT_FOUND, "no such memory", id=done["id"])
    return 200, {"ok": True, **done}


def v1_drafts(ctx):
    """What the agents wrote and nothing has published.

    They used to be written and thrown away — the social agent was the largest line in one
    company's spend and left nothing behind. Keeping them was half the fix; a client that can read
    them is the other half.
    """
    return 200, {"ok": True, **adapters.drafts_payload(ctx.store(), ctx.slug)}


def v1_drafts_post(ctx):
    """Mark one published or discarded.

    `published` is the operator's word for "this went out", not a claim that corparius sent it —
    nothing here publishes to a social channel, and saying otherwise in an API a phone will read is
    exactly the kind of promise this project refuses. What it does is stop the post counting
    against the queue, which is what lets the agent resume.
    """
    store = ctx.store()
    try:
        done = app_drafts.set_state(store, ctx.body.get("id"), str(ctx.body.get("state", "")))
    except app_errors.Refused as exc:
        field = "id" if "id" in str(exc) else "state"
        return contracts.refuse(
            400, contracts.INVALID, str(exc), field=field, allowed=list(app_drafts.STATES)
        )
    if not done["found"]:
        return contracts.refuse(404, contracts.NOT_FOUND, "no such draft", id=done["id"])
    return 200, {"ok": True, **adapters.drafts_payload(store, ctx.slug)}


# --- documents ------------------------------------------------------------------
#
# Four endpoints, and the one thing to keep straight across all of them: **a refused file is not a
# failed request.** Asking to store a `.zip` is a perfectly well-formed thing to ask; the answer is
# `stored: false` with a `reason` the client turns into a sentence. So the error envelope is reserved
# for requests that were wrong — an unknown company, a body that is not base64 — and the outcome of a
# well-formed one travels in the payload. That distinction is what lets a drop zone report six files
# stored and one skipped in a single pass instead of a banner saying the upload failed.
#
# None of these are on a poll. `inventory` opens and extracts every file it lists, and a PDF parse on
# a polled path is the same mistake as a network probe on one — a rule this project wrote after
# `/api/providers` opened a socket on every refresh.


def v1_documents(ctx):
    """What the company has on file, and what of it an agent actually reads.

    The number that matters is not how many files exist, it is what reaches a prompt — and what that
    means changed when `documents.context` learned to build a map. It used to be "the newest files
    that fit 6 000 characters", so a company holding twelve documents could be feeding two of them to
    its agents while the other ten sat there looking like knowledge.

    Now **every readable document's headings ride on every prompt**, and the budget buys the sections
    a given turn should quote. So `reaching` is every readable file, `sections` is how many titled
    parts they add up to, and `used` is what the map costs on each prompt — the part that is always
    spent. There is deliberately no single number for "how much of the body reaches a prompt": that
    is decided per turn against what the agent is about to do, and inventing an average here would be
    this card describing a retrieval nobody runs.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {"ok": True, **documents.inventory(ctx.slug)}


def v1_document_text(ctx):
    """One document's whole extracted text, with no prompt budget applied.

    The reading surface and the prompt budget are different questions. The card used to reuse the
    text an agent gets, capped at `documents.MAX_CHARS` so a thirty-page deck cannot swallow a turn —
    honest, and still the wrong answer for a person rereading their own brief.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    path = str(ctx.query.get("path", ""))
    if not path:
        return contracts.refuse(400, contracts.INVALID, "a document path is required", field="path")
    doc = documents.full_text(ctx.slug, path)
    if doc is None:
        return contracts.refuse(404, contracts.NOT_FOUND, "no such document", path=path)
    return 200, {"ok": True, "path": doc.label, **doc.as_dict(), "text": doc.text}


def v1_documents_post(ctx):
    """Store one file the operator dropped on the console.

    One file per request, deliberately: a batch would need a body ceiling sized for the worst case it
    might ever carry, would collapse ten outcomes into one answer, and would make per-file progress
    something the client invented.

    The refreshed inventory rides back with the result, so the card the operator is looking at is the
    folder as it now stands rather than as it was — and a client does not have to make a second
    request to find out what its own write did.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    try:
        # validate=True, so a body that is not base64 says so here rather than writing whatever
        # survived a lenient decode into the operator's folder.
        data = base64.b64decode(str(ctx.body.get("data", "")), validate=True)
    except ValueError:  # binascii.Error subclasses it
        return contracts.refuse(
            400, contracts.INVALID, "the file did not arrive as valid base64", field="data"
        )
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
    return 200, {
        "ok": True,
        "stored": True,
        "replaced": replaced,
        "name": path.name,
        **documents.inventory(ctx.slug),
    }


def v1_documents_delete(ctx):
    """Take one document out of the folder.

    Moved aside rather than erased, like a deleted company: the answer says where it went, so a
    misread badge is recoverable. No typed confirmation, unlike deleting a company — that gate exists
    because a company is the whole thing, and friction on a routine action buys nothing here.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
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


# --- providers ------------------------------------------------------------------
#
# **No probe is reachable from a read here.** That rule was written after `/api/providers` opened a
# socket on every refresh, and it is why `providers_payload` answers `claude_installed` from the
# filesystem and omits the Claude tier plan entirely: building the plan needs to know whether Ollama
# answers, and on a machine without it that is a connect timeout per poll — on a runner where the port
# is filtered rather than refused, long enough to fail the suite.
#
# So every probe is its own POST: `/probe` for one provider, `/models` for a catalogue, `/preflight`
# for a bounded pass over every configured tier. A client decides when to spend the operator's
# account, and the verb says so.


def v1_providers(ctx):
    """Which providers exist, which are configured, and where each tier points.

    Filesystem checks and stored settings only. A key is reported as `key_set`, never returned — the
    credentials are stored write-only, and a payload that echoed them back would put them in every
    client's cache and every proxy log.
    """
    return 200, adapters.providers_payload()


def v1_providers_post(ctx):
    """Save keys, tier targets and the three toggles this panel owns.

    Through `adapters.set_env`, which since the sixth divergence goes through
    `app_settings.validate` — so `CORP_SESSION_TOKEN_BUDGET="not-a-number"` is refused here exactly as
    it is on `/api/v1/settings`, where it used to be stored verbatim and leave `cfg.get_int` answering
    the caller's fallback.

    The refusal is a list of sentences joined by the service, so `detail.errors` carries them apart
    rather than as one string a client would have to split on "; ".
    """
    result = adapters.set_env(ctx.state, dict(ctx.body.get("values", {})))
    if result.get("ok") is False:
        return contracts.refuse(
            400,
            contracts.INVALID,
            str(result.get("error", "some values were refused")),
            errors=[e.strip() for e in str(result.get("error", "")).split(";") if e.strip()],
        )
    return 200, {"ok": True, **result}


def v1_provider_models(ctx):
    """What a provider advertises, with what a preflight actually proved marked.

    One call into `adapters.provider_models`, which is where the measurement lives: 10 of 18 NVIDIA
    catalogue entries answered 404 with a real key, so the proven set is the part worth trusting.

    `ok: false` here is a provider that did not answer, not a request that was wrong — so it is a 200
    with the proven list, the same distinction as a refused document.
    """
    name = str(ctx.body.get("name", ""))
    if name not in OPENAI_COMPAT_PROVIDERS:
        return contracts.refuse(404, contracts.NOT_FOUND, f"no provider called {name!r}", name=name)
    return 200, adapters.provider_models(ctx.store(), name)


def v1_provider_probe(ctx):
    """One real call to one provider, because the operator asked.

    A POST for the reason every probe here is a POST: it spends a request on their account. The result
    is a report, not a status code — "your key is rejected" is a successful probe.
    """
    name = str(ctx.body.get("name", ""))
    if name not in OPENAI_COMPAT_PROVIDERS:
        return contracts.refuse(404, contracts.NOT_FOUND, f"no provider called {name!r}", name=name)
    return 200, {"ok": True, "result": provider_check.check(name, lang=ctx.lang)}


def v1_tiers_recommend(ctx):
    """Fill every tier from the providers actually connected, and turn mock off.

    The trap this exists to close: the defaults leave tiers pointing at providers nobody configured,
    so a single pasted key gives a company that half works. This writes a coherent routing over what
    is connected — and never a tier a preflight has shown that key cannot call, which is what `proven`
    is for.

    `rank` and `recommended_routing` are `domain/` policy over measurements, taking candidates,
    catalogue and scores as parameters and doing no I/O. That is stage 5's one real inversion, and it
    is why this handler can be a call rather than a calculation.
    """
    from ..providers import modelinfo, preflight
    from ..providers.routing import recommended_routing

    local_trivial, _why = hardware.recommended_local(ctx.store(), state.fresh_settings())
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
        return contracts.refuse(
            409,
            contracts.CONFLICT,
            "connect a free provider first (Groq or Cerebras are the quickest)",
        )
    result = adapters.set_env(
        ctx.state, {"CORP_LLM_MOCK": "false", "CORP_CLOUD_ENABLED": "true", **routing}
    )
    if result.get("ok") is False:
        return contracts.refuse(400, contracts.INVALID, str(result.get("error", "refused")))
    return 200, {"ok": True, **result, "routing": routing}


def v1_preflight(ctx):
    """Call every configured model once, for eight tokens, and remember what answered.

    A POST, never a GET on a polled path: each probe is a real generation on the operator's own
    account. The doctor reads what this leaves behind and never measures — the same split as the
    hardware bench.

    `skipped` is named rather than dropped, because a preflight that covers three of six tiers and
    reports success is worse than one that admits its reach.
    """
    from ..providers import preflight

    s = state.fresh_settings()
    if s.llm_mock:
        return contracts.refuse(
            409, contracts.CONFLICT, "mock mode is on, so there is no provider to call"
        )
    report = preflight.run(s, timeout=int(ctx.body.get("timeout", preflight.TIMEOUT)))
    preflight.save(ctx.store(), report)
    return 200, {
        "ok": True,
        **report.as_dict(),
        "skipped": [{"tier": t, "model": m} for t, m in preflight.skipped(s)],
    }


def v1_ollama(ctx):
    """What is installed locally, what is missing, and what this machine can carry.

    The cached measurement only — `hardware.profile` reads what a bench left behind and never runs
    one, so this stays cheap enough for a client to ask on arrival.

    **The pull is deliberately not here.** `adapters.ollama_pull` tracks progress in
    `UiState.pulls`, an in-process dict that does not survive a restart — which is the state schema 19
    built the `jobs` table to replace. Publishing a `pulling` flag in v1 would be publishing a field
    that lies the moment the console is restarted, so the pull moves to a durable job before it gets a
    v1 spelling. The legacy route still serves the shipped page.
    """
    result = ollama_setup.status(lang=ctx.lang)
    settings = state.fresh_settings()
    profile = hardware.profile(ctx.store(), max_age_days=settings.bench_max_age_days)
    choice, why = hardware.recommended_local(ctx.store(), settings, result.get("installed"))
    return 200, {
        "ok": True,
        **result,
        "machine": profile,
        "local_model": choice,
        "local_reason": why,
    }


def v1_claude(ctx):
    """Whether the Claude CLI is here and already authenticated. Filesystem only.

    `desktop_installed` exists so the card can say "that is the chat app, not the CLI" — the single
    most common confusion in this setup — without costing a probe.
    """
    return 200, {
        "ok": True,
        "installed": claudecli.installed(),
        "desktop": claudecli.desktop_installed(),
        "ready": claudecli.already_on(),
        "install_cmd": claudecli.INSTALL_CMD,
        "hard_tier": claudecli.HARD_TIER,
    }


def v1_claude_setup(ctx):
    """One press: prove the CLI answers, then point the tiers at it.

    The proof comes first and the settings are only written if it passes — never switch a company to a
    provider that will not answer. Free providers, when connected, keep the trivial and normal tiers:
    a subscription is metered in usage windows, and a social post every two hours is not what those
    windows are for.
    """
    result = adapters.claude_setup(ctx.state, all_tiers=bool(ctx.body.get("all_tiers")))
    if result.get("ok") is False:
        return contracts.refuse(
            409,
            contracts.CONFLICT,
            str(result.get("error", "the Claude CLI did not answer")),
            check=result.get("check", {}),
        )
    return 200, {"ok": True, **result}


def v1_machine(ctx):
    """What the pull and the sweep are doing, read from the job rows.

    Both survive a restart now, which is the whole point: a console killed mid-sweep leaves a `running`
    row that the next process marks `interrupted` at startup, and a client is told that rather than
    told nothing. Nothing is resumed — hundreds of paid calls should not restart themselves — and
    "interrupted, start it again" is the honest answer.

    Alongside them, what a sweep has already proved. Every verdict is written the moment it arrives, so
    this is useful mid-sweep and after one that failed at the end.
    """
    from ..providers import preflight

    store = ctx.store()
    known = store.known_probes()
    tally: dict[str, int] = {}
    oldest = 0.0
    for row in known:
        tally[row["state"]] = tally.get(row["state"], 0) + 1
        oldest = max(oldest, time.time() - float(row["ts"] or time.time()))
    return 200, {
        "ok": True,
        **app_setup.view(store),
        "known": len(known),
        "tally": tally,
        "usable_by_provider": {k: len(v) for k, v in preflight.known(store).items()},
        # A verdict is a measurement and measurements age. Reported so nobody reads a six-month-old
        # `blocked` as current fact.
        "oldest_days": int(oldest / 86400),
        "worth_rechecking": len(preflight.stale(store)),
    }


def v1_ollama_pull(ctx):
    """Start pulling the models the tiers need, as a durable job.

    Gigabytes and minutes, so it runs in a thread — but the *record* is a row, so a phone can watch a
    pull this console started and a restart reports `interrupted` instead of forgetting.

    The work is `app_setup.run_pull`, not a closure here: a terminal could run the same function in the
    foreground, which is the thing `adapters.start_run` did not arrange and `cli/operate.cmd_run` had
    to duplicate 25 lines to work around.
    """
    store = ctx.store()
    try:
        claim = app_setup.start_pull(store, list(ctx.body.get("models", [])))
    except app_errors.Refused as exc:
        return contracts.refuse(409, contracts.CONFLICT, str(exc))
    threading.Thread(
        target=app_setup.run_pull,
        args=(store, claim["job"], claim["models"]),
        daemon=True,
        name="corparius-ollama-pull",
    ).start()
    return 200, {"ok": True, **claim}


def v1_sweep_post(ctx):
    """Start, price, or stop a sweep of every configured provider.

    `{"estimate": true}` answers how many calls it would make **without making any**, and that is not a
    convenience: NVIDIA alone advertises 102 models, and an operator pressing "check everything" is
    spending their own money and their own rate limits. They get the number first.

    `{"stop": true}` writes `cancel_requested`, a column rather than an event — which is what lets a
    phone stop a sweep this console started, and the same mechanism the plan names for runs.
    """
    from ..providers import preflight

    store = ctx.store()
    if ctx.body.get("stop"):
        return 200, {"ok": True, **app_setup.stop(store, app_setup.KIND_SWEEP)}
    if ctx.body.get("estimate"):
        return 200, {"ok": True, **preflight.estimate()}
    try:
        claim = app_setup.start_sweep(
            store,
            state.fresh_settings(),
            limit=int(ctx.body.get("limit", 0) or 0),
            timeout=int(ctx.body.get("timeout", 0) or 0),
        )
    except app_errors.Refused as exc:
        return contracts.refuse(409, contracts.CONFLICT, str(exc))
    threading.Thread(
        target=app_setup.run_sweep,
        args=(store, claim["job"], int(ctx.body.get("limit", 0) or 0)),
        daemon=True,
        name="corparius-preflight-sweep",
    ).start()
    return 200, {"ok": True, **claim}


def v1_pull_stop(ctx):
    """Stop after the current model.

    Not mid-download: `ollama pull` has no resumable stop and killing one halfway leaves a partial blob
    the daemon refuses to use. Between models is the honest granularity, and saying so beats a button
    that looks immediate and is not.
    """
    return 200, {"ok": True, **app_setup.stop(ctx.store(), app_setup.KIND_PULL)}


# --- going live: payments, hosting, the site --------------------------------------


def v1_payments(ctx):
    """Money actually received.

    **Not for a poll**, and this is the one v1 read where that has to be said rather than derived from
    the payload: with `STRIPE_API_KEY` set it lists charges over HTTPS, on the operator's own account
    and rate limit. The shipped page has this right already — `loadPayments()` is in its boot sequence
    and its five-second interval calls `refresh()` alone — and a v1 client must do the same.

    Without a key it answers a deterministic mock, so a console always has something honest to show
    rather than an empty card that could mean either "no sales" or "not configured".
    """
    return 200, {"ok": True, **stripe_payments()}


def v1_golive(ctx):
    """The three things between a company that simulates and one that can take money.

    A checkout link, a mail account, a public address — as booleans plus the live URL, so one card can
    walk an operator from nothing to selling. Filesystem and config only: `payment` reads the company's
    own offer or the bootstrap link, `mail` reads two settings, and `hosting` reads a `.published`
    marker. Nothing here opens a socket, which is why it *can* sit next to a polled resource.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, adapters.golive_status(ctx.slug)


def v1_site(ctx):
    """Whether the sales site is built, and **which** site the client is about to show.

    `owned` is the field that matters. A company under version control has its own site folder, and
    the console once previewed the generated path while `cmd_deploy` published the owned one — the
    second live divergence this restructuring found. Reporting which of the two is on screen is what
    stops a preview being silently a different page from the one that goes out.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
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
        "owned": owned is not None,
        "pages": sorted(p.name for p in owned.glob("*.html")) if owned else [],
    }


def v1_site_post(ctx):
    """Build the sales site from the company config.

    `headline` is optional and empty means *let the agent write one*: passing the empty string through
    as a headline would replace a written line with nothing, which is the difference between "I have no
    preference" and "say nothing here".
    """
    company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    out_dir = paths.site_dir(state.fresh_settings().data_path, ctx.slug)
    headline = str(ctx.body.get("headline", "")).strip()
    sitegen.build_site(company, str(out_dir), headline=headline or None, store=ctx.store())
    return 200, {"ok": True, "built": True}


def v1_repo(ctx):
    """Is this company versioned, and could it be. Read-only."""
    return 200, adapters.repo_status(ctx.slug)


def v1_repo_create(ctx):
    """Version this company and push it, from the console.

    The route that had to exist before `publish_production_code` could stop telling an operator to
    open a terminal — which a test caught it doing, and which is the rule this product holds itself
    to: corparius does its own work.
    """
    return adapters.create_repo(ctx.state, ctx.slug)


def v1_repo_resolve(ctx):
    """Settle a diverged company repository, from the console.

    The point of the endpoint is what the operator does *not* do: no terminal, no `git pull
    --rebase`, no path to copy out of a notice. They pick which version of their own file survives
    and corparius does the fetching, the rebasing and the push.
    """
    return adapters.resolve_repo(ctx.state, ctx.slug, str(ctx.body.get("keep", "mine")))


def v1_deploy(ctx):
    """Publish it, through whichever provider is configured.

    `app_publish.publish` is the service, and it is the one the *second* live divergence was about: the
    console honoured `paths.owned_site(slug)` and `cmd_deploy` always built the generated path, so on
    the owner's own company the two published different directories and both reported success.
    """
    return adapters.deploy(ctx.state, ctx.slug)


# --- plugins and skills ----------------------------------------------------------


def v1_plugins(ctx):
    """What is installed, what the registry offers, and what this company knows in prose.

    Two things on one tab because they are the same act from an operator's side: extending what
    corparius can do. A plugin adds a provider or a tool through one of seven declared seams; a skill
    adds knowledge to a prompt. Neither is code corparius wrote.

    `unscoped` is the number that matters and the reason this read exists. A skill naming no tool rides
    on **every prompt of every agent** — measured at 3 815 characters a turn on the owner's own
    company — and until the panel existed the console could report the cost and offer nothing to do
    about it. `always_on_chars` is that bill, for the whole set.
    """
    company, refusal = adapters.for_company(ctx.slug) if ctx.slug else (None, None)
    if refusal:
        return refusal
    return 200, {"ok": True, **adapters.plugins_payload(ctx.slug or "")}


def v1_plugins_post(ctx):
    """Enable, disable, remove, or install a **verified** plugin.

    Installing an unverified one is deliberately unreachable from any client: that path is CLI-only,
    behind an explicit opt-in, because it runs unaudited third-party code. A console button for it
    would be a button that reads as ordinary and is not.

    `restart_required` is always true and always reported. A seam is bound at import, so a plugin
    enabled now changes nothing until the process restarts — and a panel that said "Done" without
    saying that would leave an operator waiting for a provider that is not going to appear.
    """
    result = adapters.plugins_action(ctx.body)
    if result.get("ok") is False:
        return contracts.refuse(400, contracts.INVALID, str(result.get("error", "refused")))
    return 200, result


def v1_skill_scope(ctx):
    """Give a skill a tool list, so it stops riding every prompt.

    The one write this panel does, and the reason `app_skills.scope` exists: `corparius skills list`
    reported the cost of an unscoped skill from a terminal while offering nothing to do about it.

    A skill declaring `always:` is left alone by the badge but not by the bill — an always-on guardrail
    is a deliberate choice, and a warning on a deliberate choice is a warning an operator learns to
    ignore. It still counts in `always_on_chars`.
    """
    try:
        out = app_skills.scope(
            ctx.slug or "",
            str(ctx.body.get("name", "")),
            list(ctx.body.get("tools") or []),
            state.fresh_settings(),
        )
    except app_errors.Refused as exc:
        return contracts.refuse(400, contracts.INVALID, str(exc), field="tools")
    log.info("skill %s scoped to %s", out["name"], ", ".join(out["tools"]))
    return 200, {"ok": True, **out, **adapters.plugins_payload(ctx.slug or "")}


def v1_chat(ctx):
    """The conversation this company is having with its CEO.

    A read, and it answers after a restart — which is the whole of schema 21. It was
    `UiState.chats`, a deque in the console's process, so a phone could not read what the console had
    said and closing the console lost the exchanges in which the CEO paused a role or set a focus.
    Those are the turns an operator most wants to look back at.

    Bounded by rows, and the bound is the client's to choose within reason: `HISTORY_KEPT` is what a
    *prompt* is built from, and a person scrolling back is a different question. The table keeps
    everything — the same distinction documents already make between `MAX_CHARS` and reading a file.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    limit = int(ctx.query.get("limit", chat_store.HISTORY_KEPT) or chat_store.HISTORY_KEPT)
    return 200, {
        "ok": True,
        "history": ctx.store().chat_history(ctx.slug, limit=min(max(limit, 1), 200)),
    }


def v1_chat_post(ctx):
    """Say something to the CEO, and get the reply plus whatever it actually did.

    The reply and the action are two halves of one answer. `directives.apply` runs inside the service,
    so a CEO that says "I will pause the campaigns" has paused them — or the sentence is corrected.
    That shape exists because the empty promise was the failure it was written to end.

    `proposal` is the other half: an intent the CEO will not execute itself. The operator confirms with
    a button, and a client that ignored the field would hide a decision the CEO is waiting on.
    """
    message = str(ctx.body.get("message", "")).strip()
    if not message:
        return contracts.refuse(400, contracts.INVALID, "a message is required", field="message")
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, adapters.chat(ctx.state, ctx.slug, message, ctx.lang)


def v1_chat_delete(ctx):
    """Clear the conversation.

    The operator's own transcript is theirs to clear, the same argument as forgetting a memory: one
    that can only be removed by opening the database is one they do not own. Deleted rather than
    archived — a skill is knowledge the curator may want back, a conversation is one they have ended.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {"ok": True, "forgotten": ctx.store().forget_chat(ctx.slug)}


# --- settings -------------------------------------------------------------------


def v1_settings(ctx):
    """The whole field registry, described well enough for a client to render it.

    **The form is generated from this, never written out.** 80 fields across eight groups, each
    carrying its type, its group, its default, its bilingual label and help, and three facts a client
    cannot work out for itself:

      * `value` is `None` for a secret and `configured` says whether there is one. A payload that
        echoed a credential would put it in every client's cache and every proxy log.
      * `source` names the layer that answered — `env`, `dotenv`, `store` or `default` — and
        `editable` is `source != "env"`. The process environment outranks everything the console can
        write, so a field it owns is shown and disabled rather than offered and silently ignored. That
        is the same lesson the providers tab learned as `shadowed`, resolved per field instead.
      * `restart_required` for a bootstrap key: it lands in `.env` because it has to be readable
        before the store can be opened, so it applies on the next start and saying so is the
        difference between a setting that looks broken and one that is waiting.

    A hand-written form would be a second copy of the registry, and `tests/test_registries.py` exists
    because this project has already paid for that twice.
    """
    return 200, adapters.settings_payload()


def v1_settings_post(ctx):
    """Write settings, or clear them.

    `unset` is separate from an empty value because they mean different things here: clearing a
    registry field lets the layer below show through again, and that is what an operator asking for
    the default wants. (A provider credential is the opposite — `app_settings.CREDENTIALS` keeps a
    blank one stored, because a cleared row would let `.env` resurrect a key they just revoked.)

    Every refusal is a sentence per field, and `detail.errors` carries them apart rather than joined,
    so a client can put each one next to the input that caused it instead of showing one banner.
    """
    result = adapters.set_settings(
        ctx.state, dict(ctx.body.get("values", {})), list(ctx.body.get("unset", []))
    )
    if result.get("ok") is False:
        return contracts.refuse(
            400,
            contracts.INVALID,
            str(result.get("error", "some values were refused")),
            errors=[e.strip() for e in str(result.get("error", "")).split(";") if e.strip()],
        )
    return 200, {"ok": True, **result}


def v1_backup(ctx):
    """Zip the store and every company config.

    On the settings tab rather than beside the audit log, which is where the shipped page put it: it
    is a maintenance action, and "by layer, not by page" is what keeps a tab from being a reason for
    unrelated things to live together.

    The warning travels with the answer in both languages, and it is not boilerplate: no API key
    leaves in plaintext — secrets are encrypted or blanked and `REDACTED.txt` names what to re-enter —
    but the archive still holds the operator's companies and their journal. A client that offered this
    without saying so would be offering a file the operator does not know the contents of.
    """
    path = backup.make_backup(state.fresh_settings().data_path)
    return 200, {
        "ok": True,
        "name": path.name,
        "size": path.stat().st_size,
        "warning": {"en": backup.WARNING_EN, "fr": backup.WARNING_FR},
    }


def v1_jobs(ctx):
    """Work this company has done or is doing, newest first.

    The resource a client polls to find out whether the run it started is still going — and, after
    a restart it did not witness, that the answer is `interrupted` rather than silence. It is a
    read, so it carries an ETag like every other v1 GET.
    """
    _company, refusal = adapters.for_company(ctx.slug)
    if refusal:
        return refusal
    return 200, {
        "ok": True,
        "jobs": [
            adapters.publishable_job(j) for j in ctx.store().list_jobs(company=ctx.slug, limit=20)
        ],
    }


def v1_runs_post(ctx):
    """Start a run, durably. The first v1 write, and the one a phone needs.

    `Idempotency-Key` is honoured here rather than being advice in a document: a retry over a bad
    connection gets the same job back with `created: false`, so a client that never saw the first
    answer cannot start a second run by asking again.
    """
    ticks = max(1, min(int(ctx.body.get("ticks", 6)), 48))
    status, payload = adapters.start_run(
        ctx.state,
        ctx.slug,
        ticks,
        loop=bool(ctx.body.get("loop")),
        lang=ctx.lang,
        key=ctx.idempotency_key,
    )
    if status == 409:
        return contracts.refuse(
            409, contracts.CONFLICT, payload["error"], job=payload.get("job", "")
        )
    if status == 404:
        return contracts.refuse(404, contracts.UNKNOWN_COMPANY, payload["error"], slug=ctx.slug)
    return status, payload


def v1_runs_stop(ctx):
    """Ask the run to stop, from anywhere.

    The durable half of the signal is a column, which is what makes this work at all from a client
    that is not the process doing the running.
    """
    status, payload = adapters.stop_run(ctx.state, ctx.slug)
    if status == 404:
        return contracts.refuse(404, contracts.NOT_FOUND, payload["error"], slug=ctx.slug)
    return status, payload


def session(ctx):
    # Tells the page whether it must send X-Corp-Token. It never serves the
    # token itself.
    return 200, {"ok": True, "token_required": bool(cfg.get("CORP_UI_TOKEN", "").strip())}


def ollama_get(ctx):
    """The legacy spelling, and the pull's progress now comes from the job row.

    It read `ctx.state.pulls`, so a console restarted mid-download reported no pull at all. The row
    says `running` with its last line, or `interrupted` — which is the answer an operator needs, and
    the one an in-process dict could never give.
    """
    result = ollama_setup.status(lang=ctx.lang)
    pull = app_setup.view(ctx.store())["pull"]
    if pull.get("state") == "running":
        result = {**result, "detail": pull.get("progress") or "pulling...", "pulling": True}
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
    return 200, {"ok": True, **adapters.drafts_payload(ctx.store(), ctx.slug)}


def drafts_post(ctx):
    """Mark one published or discarded.

    `published` is the operator's word for "this went out", not a claim that
    corparius sent it — nothing here publishes to a social channel. It stops the
    post counting against the queue, which is what lets the agent resume.

    The flat `error` string is the legacy shape and stays: the shipped page reads `data.error` as a
    string, so an object here renders "[object Object]" on the failures an operator most needs to
    read. Same service underneath as the v1 spelling, different refusal — which is what a version is.
    """
    store = ctx.store()
    try:
        done = app_drafts.set_state(store, ctx.body.get("id"), str(ctx.body.get("state", "")))
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    if not done["found"]:
        return 404, {"ok": False, "error": "no such draft"}
    return 200, {"ok": True, **adapters.drafts_payload(store, ctx.slug)}


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


# What the built console is allowed to be made of. Narrower than `SITE_TYPES` on purpose: this
# directory is produced by `npm run build` and nothing else, so anything outside this list arriving
# in it means the build changed shape and somebody should look, rather than it being served.
CONSOLE_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".ico": "image/x-icon",
}


def console(ctx):
    """The built console, from `corparius/api/static/`.

    Two paths reach the same shell and that is deliberate: `/` is what an operator gets by typing
    nothing, and `/app/` is where the **assets** live — `base: "/app/"` in the Vite config, so a
    shell served from either path names its script and stylesheet absolutely and resolves them here.
    This handler is therefore both the shell's second address and the only one its assets have.

    Absent is a supported state and says so. The directory exists only after a build, and a source
    checkout that has never run `npm run build` still has a working console — `/` falls back to the
    single-file page, and `/legacy` serves it unconditionally. A 404 saying "not built" with the
    command in it is worth more than an empty page.

    The same two guards as the site preview, and for the same reason: resolve, then check the
    resolved path is still inside the root. Checking the text of the URL instead is what
    `..%2f..%2f.env` is for.
    """
    if not paths.console_built():
        return 404, {
            "ok": False,
            "error": "the new console is not built here. Run `npm run build` in web/, or use "
            "/legacy for the single-file console.",
        }
    root = paths.console_dir()
    rest = ctx.path[len("/app/") :] if ctx.path.startswith("/app/") else ""
    rest = unquote(rest.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
    if not rest or rest.endswith("/"):
        rest += "index.html"
    try:
        target = (root / rest).resolve()
        target.relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return 404, {"ok": False, "error": "not part of the console"}
    kind = CONSOLE_TYPES.get(target.suffix.lower())
    if kind is None:
        return 404, {"ok": False, "error": f"{target.suffix or 'that file'} is not served"}
    if not target.is_file():
        return 404, {"ok": False, "error": "not part of the console"}
    return 200, target.read_bytes(), kind


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
    """The legacy spelling. Same payload, from `adapters.plugins_payload`.

    The body moved when the v1 spelling was added, and moving it fixed a latent `NameError`: `loader`
    was bound inside `if s.skills_enabled:` and then read in a ternary guarded by the same condition —
    safe today, unbound the moment anyone rearranges it.
    """
    return 200, {"ok": True, **adapters.plugins_payload(ctx.slug or "")}


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
    """The legacy spelling. Reads `chat_turns` now, like the v1 one.

    It read `ctx.state.chats`, and that field went with schema 21 — so this was an `AttributeError` on
    the shipped page's first poll of the CEO tab. `tests/test_api_version.py` caught it by asking
    whether both spellings of an endpoint reach one function, which is the second time that ratchet has
    found a live break rather than a declaration needing an update.
    """
    return 200, {"ok": True, "history": ctx.state.store().chat_history(ctx.slug)}


def companies_post(ctx):
    return 200, adapters.create_company(ctx.state, ctx.body)


def approvals_post(ctx):
    """One call into `app_approvals.decide`, which is the whole point of this rewrite.

    This handler used to carry twenty lines that two other surfaces also carried, and the three had
    drifted: it granted the standing rule and **never released the work parked on the approval**.
    An operator approved, the board still read "Held, waiting on you", and nothing moved until a run
    ticked — which they might not start because the board looked stuck.

    The payload keeps its keys so the shipped page is unchanged, and gains the two the service can
    now answer: how much was unblocked, and whether "stop asking" was refused because the company
    gates that tool by name.
    """
    store = ctx.store()
    approval_id = str(ctx.body.get("id"))
    try:
        done = app_approvals.decide(
            store,
            state.fresh_settings(),
            approval_id,
            str(ctx.body.get("decision", "")),
            note=str(ctx.body.get("note", "via console")),
            remember=str(ctx.body.get("remember", "")),
            company=state.load_company(
                str((store.get_approval(approval_id) or {}).get("company", ""))
            ),
        )
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    return (200 if done["found"] else 404), {
        "ok": done["found"],
        "remembered": done["remembered"],
        "gated": done["gated"],
        "released": done["released"],
        "error": None if done["found"] else "approval not found",
    }


def inbox_post(ctx):
    """Answer a question, or dismiss a notice. First responder wins: a second
    answer to a decided item is refused rather than overwriting one the waiting
    work has already moved on."""
    item = str(ctx.body.get("id", "")).strip()
    if not item:
        return 400, {"ok": False, "error": "id is required"}
    done = app_inbox.answer(ctx.store(), item, str(ctx.body.get("answer", "")), ctx.slug)
    return (200 if done["answered"] else 409), {
        "ok": done["answered"],
        "released": done["released"],
        "error": None if done["answered"] else "already answered, or no such item",
    }


def memory_post(ctx):
    """Pin or forget one fact. The operator owns their company's memory the same
    way they own its secrets: a wrong thing an agent wrote down must be
    removable without opening the database."""
    try:
        done = app_memory.decide(ctx.store(), ctx.body.get("id"), str(ctx.body.get("action", "")))
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    return (200 if done["found"] else 404), {
        "ok": done["found"],
        "error": None if done["found"] else "no such memory",
    }


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
    """Edit one task, or decide one proposal. The legacy spelling.

    `app_tasks.edit` directly rather than through an adapter, so the two spellings of this endpoint
    demonstrably meet at one function — `tests/test_api_version.py` reads both bodies for it. What
    the adapter held was a `try/except` turning `Refused` into a status code, which is the one part
    of this that *is* about HTTP and belongs in a handler.
    """
    try:
        changed = app_tasks.edit(
            ctx.store(),
            ctx.body.get("id"),
            title=ctx.body.get("title"),
            priority=ctx.body.get("priority"),
            target=ctx.body.get("target"),
            tool=ctx.body.get("tool"),
            decision=ctx.body.get("decision"),
            note=str(ctx.body.get("note", "via console")),
        )
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 200, {"ok": True, **changed}


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
    return adapters.stop_run(ctx.state, ctx.slug)


def run_post(ctx):
    ticks = max(1, min(int(ctx.body.get("ticks", 6)), 48))
    return adapters.start_run(
        ctx.state,
        ctx.slug,
        ticks,
        loop=bool(ctx.body.get("loop")),
        lang=ctx.lang,
        key=ctx.idempotency_key,
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
    """The legacy spelling, `/api/provider/models`. Same call, flat refusal shape.

    The body moved to `adapters.provider_models` when the v1 spelling was added: the two paths differ
    in the noun's position (`/api/provider/models` against `/api/v1/providers/models`), which is a
    rename rather than an alias — and `tests/test_api_version.py`'s `RENAMED` map requires both to
    reach one function, or the rename shipped a second implementation under a tidier name.
    """
    name = str(ctx.body.get("name", ""))
    if name not in OPENAI_COMPAT_PROVIDERS:
        return 404, {"ok": False, "error": f"unknown provider '{name}'"}
    return 200, adapters.provider_models(ctx.state.store(), name)


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
    """The legacy spelling. Same rows underneath, flat shape on top.

    `sweep` used to be `ctx.state.sweep`, an in-process dict. It is a job row now, so this answers the
    same question after a restart instead of reporting `{"running": false}` about work it has simply
    forgotten.
    """
    from ..providers import preflight

    store = ctx.state.store()
    known = store.known_probes()
    tally: dict[str, int] = {}
    oldest = 0.0
    for row in known:
        tally[row["state"]] = tally.get(row["state"], 0) + 1
        oldest = max(oldest, time.time() - float(row["ts"] or time.time()))
    seen = app_setup.view(store)
    return 200, {
        "ok": True,
        # The shipped page reads `sweep.running`, `sweep.done`, `sweep.provider`. Mapped from the row
        # rather than changing the page: this is the legacy shape, and that is what a version is.
        "sweep": {
            "running": seen["sweep"].get("state") == "running",
            "done": (seen["sweep"].get("result") or {}).get("counts", {}),
            "provider": seen["sweep"].get("progress", ""),
            "state": seen["sweep"].get("state", ""),
        },
        "known": len(known),
        "tally": tally,
        "usable_by_provider": {k: len(v) for k, v in preflight.known(store).items()},
        "oldest_days": int(oldest / 86400),
        "worth_rechecking": len(preflight.stale(store)),
    }


def sweep_post(ctx):
    """The legacy spelling: start, price, or stop a sweep. One service underneath.

    The thread and the guard moved to `app_setup`, so this and `/api/v1/preflight/sweep` cannot come to
    disagree about whether one is already running — which they could before, because the guard was this
    process's own memory.
    """
    from ..providers import preflight

    store = ctx.state.store()
    if ctx.body.get("stop"):
        return 200, {"ok": True, **app_setup.stop(store, app_setup.KIND_SWEEP)}
    if ctx.body.get("estimate"):
        return 200, {"ok": True, **preflight.estimate()}
    try:
        claim = app_setup.start_sweep(
            store,
            state.fresh_settings(),
            limit=int(ctx.body.get("limit", 0) or 0),
            timeout=int(ctx.body.get("timeout", 0) or 0),
        )
    except app_errors.Refused as exc:
        return 400, {"ok": False, "error": str(exc)}
    threading.Thread(
        target=app_setup.run_sweep,
        args=(store, claim["job"], int(ctx.body.get("limit", 0) or 0)),
        daemon=True,
        name="corparius-preflight-sweep",
    ).start()
    return 200, {"ok": True, "started": True, **claim}


def ollama_pull(ctx):
    """The legacy spelling. `app_setup.start_pull` plus a thread, same as the v1 one."""
    store = ctx.state.store()
    try:
        claim = app_setup.start_pull(store, list(ctx.body.get("models", [])))
    except app_errors.Refused as exc:
        return 200, {"ok": False, "error": str(exc)}
    threading.Thread(
        target=app_setup.run_pull,
        args=(store, claim["job"], claim["models"]),
        daemon=True,
        name="corparius-ollama-pull",
    ).start()
    return 200, {"ok": True, "pulling": claim["models"], **claim}


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

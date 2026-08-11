"""The table. Rank 6.

One tuple, read by the dispatcher, by the security tests and by the API-version ratchet. It is
the single place that answers "what does this console expose, and to whom" — which is exactly
what it did not answer when `do_GET` and `do_POST` were two if/elif chains with the token check
in one of them.

Exact matches first and prefixes only after every exact route has missed, so `/api/site` can
never be shadowed by a prefix that happens to start the same way.
"""

from __future__ import annotations

from .. import (
    documents,
)
from . import handlers
from .contracts import Route

# Exact matches, checked first.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", handlers.page, public=True),
    # The way back. `/` serves the built console once there is one, so the single-file page needs a
    # path of its own or a built install has no route to it at all.
    Route("GET", "/legacy", handlers.legacy_page, public=True),
    Route("GET", "/api/v1/meta", handlers.meta, public=True),
    # The narrow resources. `/api/overview` stays for the shipped page; these four are what a
    # second client polls, and `summary` is 2 859 bytes where the whole is 48 530.
    Route("GET", "/api/v1/summary", handlers.v1_summary, needs_slug=True),
    Route("GET", "/api/v1/tasks", handlers.v1_tasks, needs_slug=True),
    Route("GET", "/api/v1/memory", handlers.v1_memory, needs_slug=True),
    Route("GET", "/api/v1/activity", handlers.v1_activity, needs_slug=True),
    Route("GET", "/api/v1/companies", handlers.v1_companies),
    Route("GET", "/api/v1/jobs", handlers.v1_jobs, needs_slug=True),
    Route("GET", "/api/v1/drafts", handlers.v1_drafts, needs_slug=True),
    # The writes the overview tab needs. Reads moved to v1 first because that is where the cost was;
    # these move now because a v1 client has decisions to make.
    Route("POST", "/api/v1/approvals", handlers.v1_approvals_post),
    Route("POST", "/api/v1/inbox", handlers.v1_inbox_post, needs_slug=True),
    # And the writes the operations tab needs: the board, the standing rules, the memory, the
    # drafts. Each one is a decision an operator makes about work that already exists, which is
    # what separates this tab from the overview's two buttons.
    Route("POST", "/api/v1/tasks", handlers.v1_tasks_post),
    Route("POST", "/api/v1/rules", handlers.v1_rules_post, needs_slug=True),
    Route("POST", "/api/v1/memory", handlers.v1_memory_post),
    Route("POST", "/api/v1/drafts", handlers.v1_drafts_post, needs_slug=True),
    # The documents tab. Off every poll, all four: `inventory` opens and extracts every file it
    # lists, and a PDF parse on a polled path is the same mistake as a network probe on one.
    Route("GET", "/api/v1/documents", handlers.v1_documents, needs_slug=True),
    Route("GET", "/api/v1/documents/text", handlers.v1_document_text, needs_slug=True),
    Route("POST", "/api/v1/documents/delete", handlers.v1_documents_delete, needs_slug=True),
    # The one route in v1 with its own ceiling, and it belongs next to the route that needs it: a
    # global limit wide enough for a 6 MB PDF is a global limit wide enough for a flood through
    # everything else. Base64 costs a third, and the slack covers the JSON around it.
    Route(
        "POST",
        "/api/v1/documents",
        handlers.v1_documents_post,
        needs_slug=True,
        max_body=documents.MAX_UPLOAD * 4 // 3 + (1 << 16),
    ),
    # The providers tab. The reads are filesystem checks and stored settings; **every probe is its
    # own POST**, because each one spends a request on the operator's account and the verb should say
    # so. That rule was written after `/api/providers` opened a socket on every refresh.
    Route("GET", "/api/v1/providers", handlers.v1_providers),
    Route("GET", "/api/v1/ollama", handlers.v1_ollama),
    Route("GET", "/api/v1/claude", handlers.v1_claude),
    Route("POST", "/api/v1/providers", handlers.v1_providers_post),
    Route("POST", "/api/v1/providers/models", handlers.v1_provider_models),
    Route("POST", "/api/v1/providers/probe", handlers.v1_provider_probe),
    Route("POST", "/api/v1/tiers/recommend", handlers.v1_tiers_recommend),
    Route("POST", "/api/v1/preflight", handlers.v1_preflight),
    Route("POST", "/api/v1/claude/setup", handlers.v1_claude_setup),
    # The two long operations, now durable jobs. `machine` is the read a client polls while one runs —
    # and after a restart it did not witness, it reports `interrupted` rather than nothing.
    #
    # **Named `machine`, not `setup`**, and the rename came from a test. `/api/v1/setup` is a GET whose
    # path ends in a verb, and `test_mutating_routes_are_exactly_the_post_routes` flags exactly that —
    # it forbids a non-public GET ending in `/delete`, `/stop`, `/pull` or `/setup`, because
    # `POST /api/claude/setup` is why `/setup` reads as a write. The heuristic was right: a read named
    # after an action defeats the one check that keeps writes behind POST.
    Route("GET", "/api/v1/machine", handlers.v1_machine),
    Route("POST", "/api/v1/ollama/pull", handlers.v1_ollama_pull),
    Route("POST", "/api/v1/ollama/pull/stop", handlers.v1_pull_stop),
    Route("POST", "/api/v1/preflight/sweep", handlers.v1_sweep_post),
    # The settings tab. The read is the whole field registry described for rendering — a client
    # generates the form from it rather than carrying a second copy of 80 fields.
    Route("GET", "/api/v1/settings", handlers.v1_settings),
    Route("POST", "/api/v1/settings", handlers.v1_settings_post),
    Route("POST", "/api/v1/backup", handlers.v1_backup),
    # The CEO tab. Schema 21 made the conversation a table, so the read answers after a restart and a
    # phone can follow a thread the console started.
    Route("GET", "/api/v1/chat", handlers.v1_chat, needs_slug=True),
    Route("POST", "/api/v1/chat", handlers.v1_chat_post, needs_slug=True),
    Route("POST", "/api/v1/chat/forget", handlers.v1_chat_delete, needs_slug=True),
    # The plugins tab, which carries skills too: both are the operator extending what corparius can
    # do, one through a seam and one through prose in a prompt.
    Route("GET", "/api/v1/plugins", handlers.v1_plugins),
    Route("POST", "/api/v1/plugins", handlers.v1_plugins_post),
    Route("POST", "/api/v1/skills/scope", handlers.v1_skill_scope, needs_slug=True),
    # Going live. `payments` is the one v1 read that must not be polled: with a Stripe key set it lists
    # charges over HTTPS, on the operator's own account. `golive` and `site` are filesystem and config
    # only, so they may sit beside a polled resource.
    Route("GET", "/api/v1/payments", handlers.v1_payments),
    Route("GET", "/api/v1/golive", handlers.v1_golive, needs_slug=True),
    Route("GET", "/api/v1/site", handlers.v1_site, needs_slug=True),
    Route("POST", "/api/v1/site", handlers.v1_site_post, needs_slug=True),
    Route("POST", "/api/v1/deploy", handlers.v1_deploy, needs_slug=True),
    # The first v1 writes. Durable work: a client that loses the answer can ask again with the
    # same `Idempotency-Key` and will not start a second run.
    Route("POST", "/api/v1/runs", handlers.v1_runs_post, needs_slug=True),
    Route("POST", "/api/v1/runs/stop", handlers.v1_runs_stop, needs_slug=True),
    Route("GET", "/api/session", handlers.session, public=True),
    Route("GET", "/api/companies", handlers.companies_get),
    Route("GET", "/api/overview", handlers.overview, needs_slug=True),
    Route("GET", "/api/providers", handlers.providers_get),
    Route("GET", "/api/golive", handlers.golive, needs_slug=True),
    Route("GET", "/api/settings", handlers.settings_get),
    Route("GET", "/api/company", handlers.company_get, needs_slug=True),
    Route("GET", "/api/ollama", handlers.ollama_get),
    Route("GET", "/api/drafts", handlers.drafts_get, needs_slug=True),
    Route("GET", "/api/documents", handlers.documents_get, needs_slug=True),
    Route("GET", "/api/document/text", handlers.document_text, needs_slug=True),
    Route("GET", "/api/site", handlers.site_get, needs_slug=True),
    Route("GET", "/api/payments", handlers.payments_get),
    Route("GET", "/api/doctor", handlers.doctor),
    Route("GET", "/api/update", handlers.update),
    Route("POST", "/api/update/apply", handlers.update_apply),
    Route("GET", "/api/plugins", handlers.plugins_get),
    Route("GET", "/api/theme", handlers.theme_get),
    Route("GET", "/api/chat", handlers.chat_get, needs_slug=True),
    Route("POST", "/api/companies", handlers.companies_post),
    Route("POST", "/api/approvals", handlers.approvals_post),
    Route("POST", "/api/drafts", handlers.drafts_post, needs_slug=True),
    # base64 costs a third on the way in, so the ceiling is documents.MAX_UPLOAD
    # plus that plus the JSON envelope. Stated as arithmetic rather than a round
    # number, so raising the file limit cannot silently leave the route behind.
    Route(
        "POST",
        "/api/documents",
        handlers.documents_post,
        needs_slug=True,
        max_body=documents.MAX_UPLOAD * 4 // 3 + (1 << 16),
    ),
    # Keeps the tight default ceiling: it carries a path, not a file.
    Route("POST", "/api/documents/delete", handlers.documents_delete, needs_slug=True),
    Route("POST", "/api/rules", handlers.rules_post, needs_slug=True),
    Route("POST", "/api/memory", handlers.memory_post),
    Route("POST", "/api/inbox", handlers.inbox_post),
    Route("POST", "/api/tasks", handlers.tasks_post),
    Route("POST", "/api/site", handlers.site_post),
    Route("POST", "/api/deploy", handlers.deploy_post),
    Route("POST", "/api/backup", handlers.backup_post),
    Route("POST", "/api/run/stop", handlers.run_stop),
    Route("POST", "/api/run", handlers.run_post),
    Route("POST", "/api/providers", handlers.providers_post),
    Route("POST", "/api/tiers/recommend", handlers.tiers_recommend),
    Route("POST", "/api/provider/models", handlers.provider_models),
    Route("POST", "/api/settings", handlers.settings_post),
    Route("POST", "/api/plugins", handlers.plugins_post),
    Route("POST", "/api/skills/scope", handlers.skill_scope, needs_slug=True),
    Route("POST", "/api/theme", handlers.theme_post),
    Route("POST", "/api/test/mail", handlers.test_mail),
    Route("POST", "/api/test/payments", handlers.test_payments),
    Route("POST", "/api/test/claude", handlers.test_claude),
    Route("POST", "/api/claude/setup", handlers.claude_setup),
    Route("POST", "/api/claude/install", handlers.claude_install),
    Route("POST", "/api/test/provider", handlers.test_provider),
    Route("POST", "/api/preflight", handlers.preflight),
    Route("GET", "/api/preflight/sweep", handlers.sweep_get),
    Route("POST", "/api/preflight/sweep", handlers.sweep_post),
    Route("POST", "/api/ollama/pull", handlers.ollama_pull),
    Route("POST", "/api/ollama/bench", handlers.ollama_bench),
    Route("POST", "/api/company", handlers.company_post),
    Route("POST", "/api/company/delete", handlers.company_delete),
    Route("POST", "/api/chat", handlers.chat_post),
)


# Prefix matches, checked only after every exact route has missed, so /api/site
# can never be shadowed by a prefix that happens to start the same way.
PREFIX_ROUTES: tuple[Route, ...] = (
    Route("GET", "/site/", handlers.site_serve, public=True),
    # The built console. Public for the same reason `/` is: it carries no operator data, and it has
    # to load before it can ask for a token. Every request it then makes is authenticated normally.
    Route("GET", "/app/", handlers.console, public=True),
)


# Every route there is, in one name. `ROUTES` and `PREFIX_ROUTES` are two tables because they
# are matched differently — exact first, so `/api/site` can never be shadowed by a prefix that
# happens to start the same way — but anything *auditing* the surface has to see both.
#
# It did not. `tests/test_webui_security.py` asserted that every non-public route demands a
# token by iterating `ROUTES` alone, so a prefix route added non-public would have been outside
# a security check that reads as exhaustive. A partial registry is the defect this project keeps
# finding in other registries; here it was in the one guarding the token.
ALL_ROUTES: tuple[Route, ...] = ROUTES + PREFIX_ROUTES


_EXACT = {(r.method, r.path): r for r in ROUTES}


assert len(_EXACT) == len(ROUTES), "duplicate (method, path) in ROUTES"


def match(method: str, path: str) -> Route | None:
    route = _EXACT.get((method, path))
    if route is not None:
        return route
    for candidate in PREFIX_ROUTES:
        if candidate.method == method and path.startswith(candidate.path):
            return candidate
    return None

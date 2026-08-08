"""The architecture, as a test rather than as an intention.

corparius grew to 23 050 lines across 53 modules in a **completely flat** package, and
the reason that got away from everyone is that nothing was watching. There is no rule a
reviewer can point at, and no failure when a module reaches somewhere it should not.

So the rule lives here, and it is measured on every run.

**Ranks.** Every module is assigned the rank of the layer it belongs to, and a module may
import its own rank or lower — never higher. The table below *is* the target layout of
`docs/architecture-code.md`, written in a form that fails when reality drifts from it.
Today the package is flat, so the table is aspiration; as modules move into `kernel/`,
`config/`, `store/`, `providers/`, `domain/`, `app/` and `api/`, the keys become paths and
the ranks stop being aspiration.

**Deferred imports count.** This is the clause that makes the rest true. Measured on this
package: the module-scope import graph is a directed acyclic graph, and **all five import
cycles exist only because of ~60 function-local imports**. Those deferred imports are
load-bearing — remove them and the package stops loading. A rule that ignores them would
be a rule that misses every cycle it exists to prevent. So a `from . import x` inside a
function body is checked exactly like one at the top of the file, and deferring goes back
to being what it should be: a start-up cost optimisation, not an escape hatch.

**The ratchet.** Each rule ships with the exact set of violations that exist today, and
asserts `observed == known`. A new violation fails, **and so does a violation that was
fixed without being struck off the list**. Both ends of the wire, which is how every other
registry in this project is kept honest (see test_registries.py). The lists are also the
progress counter for the restructuring: they only ever get shorter.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path("corparius")

# --- the target layout, as ranks ---------------------------------------------
#
# 0 kernel     stdlib only, and no corparius import at all
# 1 config     settings resolution, the field registry, permissions
# 2 store      the only place sqlite3 belongs
# 3 providers  the outside world: models, mail, deploys, repos, leads, hardware
# 4 domain     the business, with no host concern at all
# 5 app        use cases the API and the CLI both call
# 6 interfaces transport: HTTP, CLI, MCP. Nothing imports these.
RANKS: dict[str, int] = {
    # 0 — kernel
    "kernel/__init__": 0,
    "kernel/i18n": 0,
    "kernel/crypto": 0,
    "kernel/dotenv": 0,
    "kernel/vectors": 0,
    "kernel/text": 0,
    "kernel/proc": 0,
    "kernel/paths": 0,
    "kernel/records": 0,
    "kernel/httpkit": 0,
    "inbox": 0,
    # Rank 1, not 0, and deliberately: `secretbox` kept the policy — where the passphrase
    # comes from, whether the feature is on — which is knowledge of configuration. Only the
    # cryptography went down to `kernel/crypto`, which takes the passphrase as an argument.
    # Splitting it this way left the seven callers untouched; merely *moving* the file would
    # have made all seven pass a passphrase they had no reason to hold.
    "config/secretbox": 1,
    # 1 — config
    "config/cfg": 1,
    # The declared exception: reading the settings table is one of the four layers, and you
    # cannot ask the database where the database is. `cfg` imports it directly rather than
    # through a registry — a registry that silently failed to register would make every
    # console-saved setting stop being read while the application kept working on defaults.
    "config/store_layer": 1,
    "config/__init__": 1,
    "config/settings": 1,
    # Pure data — which providers exist, what variable holds each key — plus the one function
    # that needs to know that list to read a tier string. It was in `llm.py` at rank 3, and
    # that is why reading a setting loaded an HTTP client.
    "config/provider_table": 1,
    "config/settings_spec": 1,
    "config/permissions": 1,
    # 2 — store. One connection and one lock on the facade, a mixin per table beside it, and
    # the schema on its own. `store/base.py` holds the contract a mixin may assume.
    "store/__init__": 2,
    "store/base": 2,
    "store/schema": 2,
    "store/actions": 2,
    "store/approvals": 2,
    "store/decisions": 2,
    "store/directives": 2,
    "store/drafts": 2,
    "store/inbox": 2,
    "store/machine": 2,
    "store/memory": 2,
    "store/model_catalogue": 2,
    "store/model_probes": 2,
    "store/outreach": 2,
    # The three reads that name more than one table, and therefore belong to none of them.
    "store/reports": 2,
    "store/rules": 2,
    "store/settings": 2,
    "store/skill_usage": 2,
    "store/state": 2,
    "store/tasks": 2,
    "store/token_usage": 2,
    # 3 — providers. The folder is the point: rank 3 was seventeen hand-maintained
    # entries here, and is now derivable from the path.
    "providers/__init__": 3,
    "providers/claudecli": 3,
    "providers/companyrepo": 3,
    "providers/deliverability": 3,
    "providers/deploy": 3,
    "providers/enrich": 3,
    "providers/hardware": 3,
    "providers/integrations": 3,
    "providers/leadsource": 3,
    "providers/llm": 3,
    "providers/mailbox": 3,
    "providers/modelinfo": 3,
    "providers/ollama_setup": 3,
    "providers/preflight": 3,
    "providers/provider_check": 3,
    "providers/routing": 3,
    "providers/signals": 3,
    "providers/sitecheck": 3,
    # 4 — domain
    # The roster is data — roles, cadences, playbooks naming tools as strings — and it is
    # free to import. It was the first 150 lines of `agents.py`, and that adjacency is what
    # made {agents, tools/effects, tools/registry} a cycle: the effects read the roster, so
    # they imported the executor, which imports the registry, which imports the effects.
    "roster": 4,
    "agents": 4,
    "tools/__init__": 4,
    # Forty declarations, no callable. Six of the eight consumers of the old flat registry
    # only ever wanted a name, and paid an SMTP client for it.
    "tools/spec": 4,
    "tools/effects": 4,
    "tools/registry": 4,
    "company": 4,
    "documents": 4,
    "skills": 4,
    "skillimport": 4,
    "structured": 4,
    "hitl": 4,
    "orchestrator": 4,
    # The maintenance half of the learning loop. Rank 4 and host-free: it moves a folder and
    # reads a table through the store it is handed, and calls no model — deliberately, because
    # merging two skills is the one operation here that can lose meaning.
    "curator": 4,
    # Rank 4 since the split: what is left is policy — a token ceiling, a loop guard, a
    # spend-velocity breaker. It sat at rank 0 only because `cosine` and `hash_embed` were
    # in the same file, which is what made `store` (rank 2) import it.
    "safety": 4,
    "sitegen": 4,
    "apps": 4,
    # 5 — app: the use cases, with no transport attached, so the console and the command line
    # both reach them. `tests/test_app_layer.py` holds the two rules that keep this from being
    # a folder of renamed handlers: no `Ctx` parameter, and no transport error raised.
    "app/__init__": 5,
    "app/settings": 5,
    "app/errors": 5,
    "app/tasks": 5,
    "app/publish": 5,
    "app/companies": 5,
    "app/chat": 5,
    "app/directives": 5,
    "app/mail": 5,
    "app/skills": 5,
    "app/overview": 5,
    "app/support": 5,
    "app/meta": 5,
    "doctor": 5,
    "backup": 5,
    "selfupdate": 5,
    "update_check": 5,
    "appexport": 5,
    "plugins": 5,
    # 6 — interfaces
    # Stage 6's second half. `webui.py` was one module of 2 468 lines that was the console, its
    # business logic, its dotenv writer, its HTTP server and its route table at once; these six
    # import in a straight line and never back. `contracts` is separate from `routes` for that
    # reason alone — a `Route` next to `ROUTES` would make `handlers` import the table that
    # imports it, and within one rank the ranks would not have caught it.
    "api/__init__": 6,
    "api/state": 6,
    "api/contracts": 6,
    "api/adapters": 6,
    "api/handlers": 6,
    "api/routes": 6,
    "api/server": 6,
    "appserver": 6,
    # Stage 7. `cli.py` was 1 120 lines with a `main()` of 203 that was the whole argparse tree;
    # each group now registers its own parsers, which is what made `tests/test_cli_registry.py`
    # possible — the tree can be built and asked questions without running a command.
    "cli/__init__": 6,
    "cli/__main__": 6,
    "cli/support": 6,
    "cli/lifecycle": 6,
    "cli/operate": 6,
    "cli/backlog": 6,
    "cli/publish": 6,
    "cli/configure": 6,
    "cli/prove": 6,
    "cli/maintain": 6,
    "cli/console": 6,
    "appcli": 6,
    "skillcli": 6,
    "plugincli": 6,
    "secretscli": 6,
    "mcp_server": 6,
    # The composition root may reach anywhere; that is what a composition root is for.
    "__init__": 6,
}

# Every edge that points upward. **Empty**, and that is the point of writing it as a ratchet:
# it started at four and each one was struck out by the step of the plan that named it.
#
#   ("secretbox", "cfg")       stage 1, by splitting crypto from policy
#   ("backup", "webui")        stage 1, by moving the dotenv writer to kernel/dotenv.py
#   ("settings_spec", "llm")   stage 2, by moving the provider table to config/
#   ("doctor", "appserver")    stage 3, by moving `key_env` to `apps`, where the app is
#
# An empty set is not a licence: `_ratchet` still asserts `observed == known`, so the next
# upward import fails here with nothing to hide behind.
KNOWN_RANK_VIOLATIONS: frozenset[tuple[str, str]] = frozenset()

# The strongly connected components that still exist. **One**, of the five the restructuring
# started with, and every one that died says the same thing: the cycle was never the problem,
# it was the symptom of a module carrying two things.
#
#   {cfg, secretbox}                        stage 1 — cryptography split from policy
#   {appserver, backup, doctor, selfupdate, webui}
#                                           stage 1 — a body ceiling and a Host parser are
#                                           not console features (kernel/httpkit)
#   {agents, company, tools}                stage 3 — a data table and the machine that
#                                           consumes it were one file (roster)
#   {claudecli, llm, preflight}             stage 5 — `rank` and `recommended_routing` are
#                                           decisions, living inside what they decide about
#
# Every one of them lived on a *deferred* import, which is why the rules above read function
# bodies, and why this list was possible to write at all.
# **Empty**, like KNOWN_RANK_VIOLATIONS above, and for the same reason it is written as a
# ratchet rather than a comment: each of the five was struck off by the step that named it, and
# `observed == known` still holds — so the next cycle fails here with nothing to hide behind.
#
#   {cfg, secretbox}                stage 1 — cryptography split from policy
#   {appserver, backup, doctor, selfupdate, webui}
#                                   stage 1 — a body ceiling and a Host parser are not console
#                                   features (kernel/httpkit)
#   {agents, company, tools}        stage 3 — a data table and the machine that consumes it
#                                   were one file (roster)
#   {claudecli, llm, preflight}     stage 5 — `rank` and `recommended_routing` are decisions,
#                                   living inside what they decide about
#   {appcli, cli, secretscli}       stage 7 — two lines: `cli._store` was the only place that
#                                   opened a store, so two sub-CLIs reached back into the module
#                                   that imports them
#
# The pattern held every time: **the cycle was never the problem, it was the symptom of a module
# carrying two things.** Not one of the five was fixed by breaking an edge — each died when the
# thing that did not belong moved out.
KNOWN_CYCLES: frozenset[tuple[str, ...]] = frozenset()

# Rank 4 may not touch the host at all. Two exceptions today, same cause.
BANNED_IN_DOMAIN = ("requests", "subprocess", "sqlite3", "smtplib", "imaplib", "socket")
KNOWN_IMPURE: frozenset[tuple[str, str]] = frozenset(
    {
        # Both catch `requests.RequestException` from the layer below. The fix is not to
        # stop catching it: it is for the provider layer to raise its own error, and
        # `llm.ProviderError` already exists — `apps.py:223` catches both. Stage 5.
        ("apps", "requests"),
        ("orchestrator", "requests"),
        # The tick loop sleeps, so it cannot be tested without real time passing. Becomes
        # a `sleep=time.sleep` default parameter, not an injected Clock ABC: two callers
        # and one fake beats an interface.
        ("orchestrator", "time.sleep"),
    }
)

# One owner per host capability. The right-hand side is where each is allowed to appear
# *today*; the target is in the comment.
OWNERS: dict[str, tuple[frozenset[str], str]] = {
    # Two of the three, stage 2: `cfg` had a read-only connection, a lock, a cache and a
    # `PRAGMA data_version` poll inside a 200-line precedence resolver. That is now
    # `config/store_layer.py`, the declared rank-1 exception. `backup` is next — it snapshots
    # the store through SQLite's own backup API, which `store/**` should own. → store/** and
    # config/store_layer.py only.
    "sqlite3": (
        frozenset(
            {
                "store/__init__",
                "store/base",
                "store/schema",
                "config/store_layer",
                "backup",
            }
        ),
        "store/** and config/store_layer",
    ),
    # Done, stage 1. Seven call sites across four modules became one wrapper that owns
    # Windows quoting, timeouts, capture and — the part that mattered — the utf-8 decoding
    # that only one of the seven had written down why it needed.
    "subprocess": (frozenset({"kernel/proc"}), "kernel/proc.py"),
    # → api/** only.
    # Done, stage 6. `webui` was the second owner; the transport now lives in `api/server`,
    # and `appserver` is the MCP server, a different door on the same product.
    "http.server": (frozenset({"api/server", "appserver"}), "api/**"),
}


# --- reading the imports ------------------------------------------------------


def _modules() -> list[Path]:
    return sorted(ROOT.rglob("*.py"))


def _key(path: Path) -> str:
    """The rank-table key for a file. A stem today, a path once the package has depth."""
    rel = path.relative_to(ROOT).with_suffix("").as_posix()
    return rel


_KEYS = frozenset(_key(p) for p in _modules())


def _resolve(base: str, dotted: str) -> str:
    """A dotted relative target to a rank-table key, or "" when it names no module of ours.

    The first version of this took `dotted.split(".")[0]`, which was right while the package
    was flat and wrong the moment it was not: `from .kernel import crypto` resolved to
    `kernel`, which is in no table, so `if target in RANKS` dropped the edge without a word.
    A layer test that silently stops seeing edges is worse than no layer test, because it
    reports success. Resolution now ends at a file that exists, or at the package
    `__init__` that a subpackage import really does execute.
    """
    parts = [p for p in (base.split("/") if base else []) + dotted.split(".") if p]
    while parts:
        candidate = "/".join(parts)
        if candidate in _KEYS:
            return candidate
        if f"{candidate}/__init__" in _KEYS:
            return f"{candidate}/__init__"
        parts.pop()  # `from .llm import ProviderError` — the tail is a symbol, not a module
    return ""


def _edges(path: Path) -> set[tuple[str, bool]]:
    """Every corparius import in a module, as (target, deferred).

    Deferred means inside a function body. It is reported rather than skipped: see the
    module docstring — every cycle in this package hides behind a deferred import.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    base = path.parent.relative_to(ROOT).as_posix()
    base = "" if base == "." else base
    inside_function: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for inner in ast.walk(node):
                inside_function.add(id(inner))
    found: set[tuple[str, bool]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        deferred = id(node) in inside_function
        # `from ..x import y` climbs out of the containing package first.
        start = base
        for _ in range(node.level - 1):
            start = start.rpartition("/")[0]
        if node.module:  # from .kernel.crypto import PREFIX
            target = _resolve(start, node.module)
            if target and target != _key(path):
                found.add((target, deferred))
        else:  # from . import cfg, paths
            for alias in node.names:
                target = _resolve(start, alias.name)
                if target and target != _key(path):
                    found.add((target, deferred))
    return found


def _third_party(path: Path) -> set[str]:
    """Banned host imports present in a module, plus `time.sleep` if it is called."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in BANNED_IN_DOMAIN:
                    found.add(head)
        elif isinstance(node, ast.ImportFrom) and node.module:
            head = node.module.split(".")[0]
            if head in BANNED_IN_DOMAIN:
                found.add(head)
    if "time.sleep(" in text:
        found.add("time.sleep")
    return found


# --- the rules ----------------------------------------------------------------


def test_every_module_has_a_rank():
    """A module with no rank is a module outside the architecture, and it would be
    exempt from every rule below without anything saying so."""
    keys = {_key(p) for p in _modules()}
    unranked = sorted(keys - set(RANKS))
    stale = sorted(set(RANKS) - keys)
    assert not unranked, f"modules with no rank: {unranked}"
    assert not stale, f"ranks naming modules that no longer exist: {stale}"


def test_no_module_imports_a_higher_rank():
    observed = set()
    for path in _modules():
        src = _key(path)
        if src not in RANKS:
            continue
        for target, _deferred in _edges(path):
            if target in RANKS and RANKS[target] > RANKS[src]:
                observed.add((src, target))
    _ratchet(observed, KNOWN_RANK_VIOLATIONS, "upward imports")


def test_the_kernel_imports_nothing_of_ours():
    """Rank 0 is the floor. It may not import corparius at all — not a lower rank,
    nothing — because that is what makes it safe to import from anywhere."""
    observed = set()
    for path in _modules():
        src = _key(path)
        if RANKS.get(src) != 0:
            continue
        for target, _deferred in _edges(path):
            if target in RANKS:
                observed.add((src, target))
    known = frozenset(e for e in KNOWN_RANK_VIOLATIONS if RANKS.get(e[0]) == 0)
    _ratchet(observed, known, "kernel reaching into the package")


def test_the_domain_touches_no_host():
    """Rank 4 is the business. `agents.py` is already host-concern-free and nothing said
    so; this turns that observation into a gate — and catches the reverse, a domain
    module that quietly grows a socket."""
    observed = set()
    for path in _modules():
        src = _key(path)
        if RANKS.get(src) != 4:
            continue
        for name in _third_party(path):
            observed.add((src, name))
    _ratchet(observed, KNOWN_IMPURE, "host concerns in the domain")


@pytest.mark.parametrize("capability", sorted(OWNERS))
def test_each_host_capability_has_one_owner(capability):
    """`sqlite3` in three modules means three places that can lock the database;
    `subprocess` in four means four places that get Windows quoting wrong differently."""
    allowed, target = OWNERS[capability]
    head = capability.split(".")[0]
    observed = set()
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        if f"import {capability}" in text or f"from {capability} import" in text:
            observed.add(_key(path))
        elif head == capability and f"\nimport {head}\n" in text:
            observed.add(_key(path))
    assert observed == set(allowed), (
        f"{capability} lives in {sorted(observed)}, declared {sorted(allowed)}. "
        f"It belongs in {target}: add it to OWNERS if the move is deliberate."
    )


def _cycles() -> set[frozenset[str]]:
    """The strongly connected components of the import graph, larger than one module."""
    graph = {_key(p): {t for t, _ in _edges(p)} for p in _modules()}
    # Tarjan, iterative: the recursive form overflows on a graph this dense.
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    found: set[frozenset[str]] = set()
    counter = 0
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(sorted(graph[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    component = set()
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.add(member)
                        if member == node:
                            break
                    if len(component) > 1:
                        found.add(frozenset(component))
    return found


def test_the_import_graph_has_exactly_the_cycles_we_declare():
    """Ranks alone do not forbid a cycle, and that gap was real: once `secretbox` became
    rank 1, an edge back to `cfg` — rank 1 — was legal again, and the cycle stage 1 exists
    to kill could have walked straight back in through the rule meant to keep it out.

    So the components are their own ratchet. Four left of the five measured when the plan
    was written; each remaining one names the stage that dissolves it.
    """
    _ratchet({tuple(sorted(c)) for c in _cycles()}, KNOWN_CYCLES, "import cycles")


def test_the_ratchet_only_ever_tightens():
    """The lists are the progress counter of the restructuring. This records where it
    stands so a reader can see it move, and fails if someone pads a list instead of
    fixing a module."""
    assert len(KNOWN_RANK_VIOLATIONS) <= 2, "upward imports should only ever decrease"
    assert len(KNOWN_IMPURE) <= 3, "domain impurities should only ever decrease"
    assert len(KNOWN_CYCLES) == 0, "cycles should only ever decrease"


def _ratchet(observed: set, known: frozenset, what: str) -> None:
    """`observed == known`, with a message that says which direction is wrong.

    Both ends: an edge that appeared has to be justified, and an edge that was fixed has
    to be struck off — otherwise the list rots into a wish, and the next reader cannot
    tell what is still true.
    """
    new = sorted(observed - set(known))
    gone = sorted(set(known) - observed)
    assert not new, f"new {what}: {new}. Fix it, or add it to the list with the reason."
    assert not gone, (
        f"{what} no longer present but still declared: {gone}. Strike them off — a stale "
        "exception hides the next real one."
    )

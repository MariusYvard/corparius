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
    "paths": 0,
    "models": 0,
    "kernel/__init__": 0,
    "kernel/i18n": 0,
    "kernel/crypto": 0,
    "kernel/dotenv": 0,
    "inbox": 0,
    # Rank 1, not 0, and deliberately: `secretbox` kept the policy — where the passphrase
    # comes from, whether the feature is on — which is knowledge of configuration. Only the
    # cryptography went down to `kernel/crypto`, which takes the passphrase as an argument.
    # Splitting it this way left the seven callers untouched; merely *moving* the file would
    # have made all seven pass a passphrase they had no reason to hold.
    "secretbox": 1,
    # `safety` holds two unrelated things and that is why a rank-2 module imports it:
    # `store` takes only `cosine` and `hash_embed`, which are vector utilities, while
    # `TokenBudget`/`LoopGuard`/`CircuitBreaker` are domain policy. It splits into
    # `kernel/vectors.py` + `domain/safety.py`; until then rank 0 is the honest rank,
    # because that is the only one consistent with who imports it.
    "safety": 0,
    # 1 — config
    "cfg": 1,
    "config": 1,
    "settings_spec": 1,
    "permissions": 1,
    # 2 — store
    "store": 2,
    # 3 — providers
    "llm": 3,
    "claudecli": 3,
    "preflight": 3,
    "modelinfo": 3,
    "provider_check": 3,
    "ollama_setup": 3,
    "hardware": 3,
    "deploy": 3,
    "companyrepo": 3,
    "leadsource": 3,
    "enrich": 3,
    "signals": 3,
    "mailbox": 3,
    "integrations": 3,
    "deliverability": 3,
    "sitecheck": 3,
    # 4 — domain
    "agents": 4,
    "tools": 4,
    "company": 4,
    "documents": 4,
    "skills": 4,
    "skillimport": 4,
    "structured": 4,
    "hitl": 4,
    "orchestrator": 4,
    "sitegen": 4,
    "apps": 4,
    # 5 — app
    "doctor": 5,
    "backup": 5,
    "selfupdate": 5,
    "update_check": 5,
    "appexport": 5,
    "plugins": 5,
    # 6 — interfaces
    "webui": 6,
    "appserver": 6,
    "cli": 6,
    "appcli": 6,
    "skillcli": 6,
    "plugincli": 6,
    "secretscli": 6,
    "mcp_server": 6,
    # The composition root may reach anywhere; that is what a composition root is for.
    "__init__": 6,
}

# Every edge that points upward today. Each one is a named step of the plan. Started at
# four; `("secretbox", "cfg")` was struck out when stage 1 split the module in two.
KNOWN_RANK_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # Stage 2. The single cheapest fix in the restructuring: `settings_spec` uses `llm`
        # on line 19 and nowhere else in 1 380 lines, to read OPENAI_COMPAT_PROVIDERS. That
        # one import drags `requests` and `subprocess` into the path of reading a setting.
        ("settings_spec", "llm"),
        # Stage 3. `doctor` wants one constant, `appserver.key_env`.
        ("doctor", "appserver"),
    }
)

# The strongly connected components that still exist, each with the stage that ends it.
# Five when the plan was written; `{cfg, secretbox}` went first, by splitting the module
# rather than moving it. Every one of these lives on a *deferred* import — which is why the
# rules above read function bodies, and why this list is possible to write at all.
KNOWN_CYCLES: frozenset[tuple[str, ...]] = frozenset(
    {
        # Stage 5. `llm` asks `preflight` what works, `preflight` asks `claudecli` and
        # `hardware`, and both ask `llm` back for the provider table.
        ("claudecli", "hardware", "llm", "preflight"),
        # Stage 3. The domain knot: `agents` needs the tools, `tools` needs the company,
        # `company` needs the tool names, `documents` needs all three.
        ("agents", "company", "documents", "tools"),
        # Stage 6. The console is imported by the things it launches. Was five modules;
        # moving the dotenv writer to `kernel/dotenv.py` took `backup` out — and
        # `selfupdate` with it, which reached the console only through `backup`.
        ("appserver", "doctor", "webui"),
        # Stage 7. All of it is `cli._store`, which two sub-CLIs import.
        ("appcli", "cli", "secretscli"),
    }
)

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
    # → store/** and config/store_layer.py only.
    "sqlite3": (frozenset({"store", "cfg", "backup"}), "store/** and config/store_layer"),
    # → kernel/proc.py only. Four call sites become one wrapper that owns Windows quoting,
    # timeouts and capture — and lets this rule forbid subprocess everywhere else.
    "subprocess": (
        frozenset({"claudecli", "companyrepo", "deploy", "llm"}),
        "kernel/proc.py",
    ),
    # → api/** only.
    "http.server": (frozenset({"webui", "appserver"}), "api/**"),
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
    assert len(KNOWN_CYCLES) <= 4, "cycles should only ever decrease"


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

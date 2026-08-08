"""Where the console and the command line do the same job, they go through the same service.

Two live bugs came out of this being untrue, and both were found by hand — reading a console
handler beside its CLI command and diffing what each one knew:

  * **the backlog.** The console validated the agent and the tool and called
    `executable_fields` on approval; `cmd_task` called `store.update_task` directly and did
    none of it. Approving from a terminal left the task with no tool, so it closed
    "done (no tool mapped)" having done nothing — 24 tasks for one role, 22 of them.
  * **publishing.** The console honoured `paths.owned_site(slug)`; `cmd_deploy` always built
    the generated path. On the owner's own company the console published
    `companies/vigil/site/public` and the command line published `data/sites/vigil`, and said
    it worked.

Finding those by inspection worked twice and does not scale. This file is the ratchet: a pair
that *should* share a service and does not has to be declared, with a reason, so the next one
fails here instead of being found on a real company.

It also records the audit, so the next reader does not repeat it. Three findings that are **not**
bugs are in `DIFFERENT_JOBS`, and one genuine gap — no way to create a company from a terminal —
is named rather than left implicit.
"""

import ast
import re
from pathlib import Path

import pytest

# Every module that registers commands, not just `cli.py`. The four sub-CLIs add their own
# parsers and call their own services, so a scan of one file sees neither — the same partial
# registry that made `_cli_commands` blind to five of thirty-three commands, left in the other
# half of the same test. `skills scope` is what found it: declared as a pair, and reported as
# unreachable because it lives in `skillcli.py`.
# Since stage 7 the main CLI is a package, so this is a glob plus the four sub-CLIs — and the
# glob is checked below rather than trusted, because a glob that stops matching is exactly how
# the flat one in test_registries.py nearly disarmed the restructuring.
CLI_MODULES = tuple(sorted(Path("corparius/cli").glob("*.py"))) + (
    Path("corparius/appcli.py"),
    Path("corparius/plugincli.py"),
    Path("corparius/secretscli.py"),
    Path("corparius/skillcli.py"),
)
# The console is two files since stage 6 split `webui.py`: the adapters are its half of each use
# case, and two of the nine pairs are reached straight from a handler with no adapter between —
# `app_mail.check` never had a `UiState` to take, so there was nothing to extract.
CONSOLE = (Path("corparius/api/adapters.py"), Path("corparius/api/handlers.py"))

# (console service, CLI command) -> the app service both must reach.
# Adding a row here is how a pair becomes enforced; the assertion is that both sides reach it.
SHARED = {
    ("edit_task", "task"): "app_tasks.edit",
    ("deploy", "deploy"): "app_publish.publish",
    ("set_settings", "set"): "app_settings.persist",
    ("create_company", "new"): "app_companies.create",
    ("chat", "ceo"): "app_chat.once",
    ("test_mail", "mail"): "app_mail.check",
    ("delete_company", "delete"): "app_companies.delete",
    ("skill_scope", "skills"): "app_skills.scope",
    ("overview", "status"): "app_overview.build",
}

# Pairs that look like a pair and are not, with the reason. Audited by reading both sides.
DIFFERENT_JOBS = {
    ("start_run", "run"): (
        "The console starts a background thread and polls it; the CLI runs in the foreground "
        "and prints the result. Same Runtime, same arguments — a difference of purpose, not of "
        "knowledge. The console reads `state.fresh_settings()` at start time so a value saved from "
        "the page applies; on a one-shot CLI process that is the same settings object."
    ),
    ("create_company", "init"): (
        "`init` does not create a company, it stamps the state of one that exists — a different "
        "job, so not a divergence. The gap this row used to name (no CLI way to create a company "
        "at all) is closed: `corparius new` pairs with `adapters.create_company` through "
        "`app_companies.create`, and that pair is in SHARED below."
    ),
    ("ollama_pull", "bench"): (
        "`bench` measures what is installed; the pull downloads. Neighbours in the console's "
        "setup card, unrelated operations."
    ),
    ("claude_setup", "claude"): (
        "The CLI's `claude` command already calls `claudecli.setup` directly, which is the "
        "same function the console's handler wraps. The wrapper is a payload shape, not logic — "
        "worth revisiting when `app/setup.py` exists, not worth a shim now."
    ),
}


def _console_services() -> set[str]:
    """The console's own functions, route handlers included.

    Handlers were excluded at first, on the theory that a pair is service-to-command. `mail`
    disproved it: `app_mail.check` never had a `UiState`, so there was no intermediate service
    to extract and the console reaches it straight from `handlers.test_mail`. That is the
    *better* shape — one fewer hop — and excluding it would have meant the pair could not be
    declared, which is the wrong incentive.

    Including them also puts the thirty-line ceiling on handlers, where it belongs for the same
    reason: an adapter that grows logic is how two callers come to differ.

    Every top-level function of both console files. The filter used to be
    `name.startswith("_")`, which worked only because everything lived in one file where the
    underscore was how a handler was told from its neighbours. It is gone with the split, and
    good: a name-shaped filter is one more thing that can quietly stop matching.
    """
    return {
        n.name
        for path in CONSOLE
        for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef)
    }


def _cli_commands() -> set[str]:
    r"""The commands argparse actually offers, read off the parser.

    This was `re.findall(r'add_parser\("([a-z-]+)"')` over `cli.py`, and it was blind to five of
    the thirty-three: `preflight`, whose `add_parser(` is followed by a newline, and `apps`,
    `plugin`, `secrets` and `skills` — four entire sub-CLIs, because they register themselves
    from their own modules and the scan only read one file.

    Found by trusting it. It said `plugincli` had no enable/disable, so a gap was reported that
    does not exist: those three are added in a loop with a variable name. The code was right and
    the scanner was wrong, which is the worse way round — a guard that under-reports passes.

    `tests/test_readme.py` had this right already and says why: read it off the parser "rather
    than kept in a second list here — which would rot the same way the README did".
    """
    import io
    from contextlib import redirect_stdout

    from corparius import cli

    out = io.StringIO()
    with pytest.raises(SystemExit), redirect_stdout(out):
        cli.main(["--help"])
    listed = re.search(r"\{([a-z,-]+)\}", out.getvalue())
    assert listed, "could not read the command list out of --help"
    return set(listed.group(1).split(","))


def _app_calls(*paths: Path) -> set[str]:
    """Which app services these modules reach. Takes several, because the CLI is five files."""
    found = set()
    for path in paths:
        found |= {
            f"app_{mod}.{fn}"
            for mod, fn in re.findall(r"app_(\w+)\.(\w+)\(", path.read_text(encoding="utf-8"))
        }
    return found


def test_the_sources_are_still_there():
    """The guard on the guard: a moved file would make every assertion below vacuous, which is
    how the flat glob in test_registries.py nearly disarmed the whole restructuring."""
    assert all(p.is_file() for p in CONSOLE), "a console file moved"
    assert all(p.is_file() for p in CLI_MODULES), "a CLI module moved"
    # The glob's own guard. Eight command groups, `support`, `__init__` and `__main__`, plus
    # four sub-CLIs; a package that stopped being found would make every scan below read less.
    assert len(CLI_MODULES) >= 15, f"the CLI scan found {len(CLI_MODULES)} modules"
    assert len(_cli_commands()) >= 20, "the CLI command scan found almost nothing"
    assert len(_console_services()) >= 20, "the console service scan found almost nothing"


@pytest.mark.parametrize(("pair", "service"), sorted(SHARED.items()))
def test_both_callers_reach_the_shared_service(pair, service):
    """The property the two bugs violated. Not "both call something" — both call *this*."""
    console_fn, command = pair
    assert service in _app_calls(*CONSOLE), f"the console no longer reaches {service}"
    assert service in _app_calls(*CLI_MODULES), f"the command line no longer reaches {service}"


@pytest.mark.parametrize(("pair", "service"), sorted(SHARED.items()))
def test_the_console_handler_kept_no_logic_of_its_own(pair, service):
    """An adapter that grows logic is how the two sides start to differ again. The console's half
    should unpack a request and map one exception.

    Counted in **statements, not lines**, and the change has a reason. The line-count version
    tripped at 33 on `adapters.overview` — a function with **four** statements and a docstring
    explaining a defect the v1 work found in it, that `/api/overview?company=nope` answered 200
    with a phantom company. A cap that punishes writing that down is a cap pushing against this
    project's own rule: the docstrings carry the measurements, and losing them is the one thing
    the plan says not to do. Statements measure logic, which is what the guard is about.
    """
    console_fn, _ = pair
    # The name can be borne by a function in either file — `overview` is both a handler and the
    # adapter it calls — so the ceiling applies to whichever ones carry it, not to the first
    # found. Taking the first would have let the two-line handler answer for the adapter.
    sizes = {}
    for path in CONSOLE:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if getattr(node, "name", "") != console_fn:
                continue
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]  # the docstring is not logic
            sizes[f"{path.name}:{node.name}"] = sum(
                1
                for child in ast.walk(ast.Module(body=body, type_ignores=[]))
                if isinstance(child, ast.stmt)
            )
    assert sizes, f"no console function named {console_fn}"
    # 20, measured: the nine pairs run from 1 to 17 statements, and the 17 is `start_run` —
    # a thread, an event and a guard against a second run, which is genuinely the console's own
    # work and not the service's. A cap below that would be a cap on the wrong function.
    too_long = {k: v for k, v in sizes.items() if v > 20}
    assert not too_long, (
        f"{too_long} statements. A console adapter should unpack and translate; anything more "
        "belongs in the service, or the command line will not have it."
    )


def test_every_declared_pair_still_exists():
    """Both ends of the wire. A row naming a console service or a command that is gone points
    the next reader at nothing, and the exemptions rot the same way."""
    services, commands = _console_services(), _cli_commands()
    ghosts = []
    for console_fn, command in list(SHARED) + list(DIFFERENT_JOBS):
        if console_fn not in services:
            ghosts.append(f"no console service {console_fn}")
        if command not in commands:
            ghosts.append(f"no CLI command '{command}'")
    assert not ghosts, ghosts


def test_every_exemption_says_why():
    """An exemption list without reasons is a list that grows. Each of these was audited by
    reading both sides, and the reason is what stops the next reader re-auditing it."""
    for pair, reason in DIFFERENT_JOBS.items():
        assert len(reason) > 80, f"{pair} is exempt with no real reason given"


def test_the_shared_services_raise_no_status_code():
    """What makes a service shareable at all. A service returning `(400, {...})` — which two of
    these handlers used to — can only be called by something that speaks HTTP."""
    import ast as ast_mod

    for service in sorted(set(SHARED.values())):
        module = service.split(".")[0].removeprefix("app_")
        tree = ast_mod.parse(Path(f"corparius/app/{module}.py").read_text(encoding="utf-8"))
        codes = {
            node.value
            for node in ast_mod.walk(tree)
            if isinstance(node, ast_mod.Constant)
            and isinstance(node.value, int)
            and 200 <= node.value <= 599
        }
        assert not codes, f"app/{module}.py carries status codes: {sorted(codes)}"

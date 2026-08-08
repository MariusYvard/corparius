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

CLI = Path("corparius/cli.py")
WEBUI = Path("corparius/webui.py")

# (console service, CLI command) -> the app service both must reach.
# Adding a row here is how a pair becomes enforced; the assertion is that both sides reach it.
SHARED = {
    ("_edit_task", "task"): "app_tasks.edit",
    ("_deploy", "deploy"): "app_publish.publish",
    ("_set_settings", "set"): "app_settings.persist",
    ("_create_company", "new"): "app_companies.create",
    ("_chat", "ceo"): "app_chat.once",
    ("_route_test_mail", "mail"): "app_mail.check",
    ("_delete_company", "delete"): "app_companies.delete",
}

# Pairs that look like a pair and are not, with the reason. Audited by reading both sides.
DIFFERENT_JOBS = {
    ("_start_run", "run"): (
        "The console starts a background thread and polls it; the CLI runs in the foreground "
        "and prints the result. Same Runtime, same arguments — a difference of purpose, not of "
        "knowledge. The console reads `_fresh_settings()` at start time so a value saved from "
        "the page applies; on a one-shot CLI process that is the same settings object."
    ),
    ("_create_company", "init"): (
        "`init` does not create a company, it stamps the state of one that exists — a different "
        "job, so not a divergence. The gap this row used to name (no CLI way to create a company "
        "at all) is closed: `corparius new` pairs with `_create_company` through "
        "`app_companies.create`, and that pair is in SHARED below."
    ),
    ("_ollama_pull", "bench"): (
        "`bench` measures what is installed; the pull downloads. Neighbours in the console's "
        "setup card, unrelated operations."
    ),
    ("_claude_setup", "claude"): (
        "The CLI's `claude` command already calls `claudecli.setup` directly, which is the "
        "same function the console's handler wraps. The wrapper is a payload shape, not logic — "
        "worth revisiting when `app/setup.py` exists, not worth a shim now."
    ),
}


def _console_services() -> set[str]:
    """The console's own functions, route handlers included.

    Handlers were excluded at first, on the theory that a pair is service-to-command. `mail`
    disproved it: `app_mail.check` never had a `UiState`, so there was no intermediate service
    to extract and the console reaches it straight from `_route_test_mail`. That is the
    *better* shape — one fewer hop — and excluding it would have meant the pair could not be
    declared, which is the wrong incentive.

    Including them also puts the thirty-line ceiling on handlers, where it belongs for the same
    reason: an adapter that grows logic is how two callers come to differ.
    """
    return {
        n.name
        for n in ast.parse(WEBUI.read_text(encoding="utf-8")).body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_")
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


def _app_calls(path: Path) -> set[str]:
    return {
        f"app_{mod}.{fn}"
        for mod, fn in re.findall(r"app_(\w+)\.(\w+)\(", path.read_text(encoding="utf-8"))
    }


def test_the_sources_are_still_there():
    """The guard on the guard: a moved file would make every assertion below vacuous, which is
    how the flat glob in test_registries.py nearly disarmed the whole restructuring."""
    assert CLI.is_file() and WEBUI.is_file()
    assert len(_cli_commands()) >= 20, "the CLI command scan found almost nothing"
    assert len(_console_services()) >= 20, "the console service scan found almost nothing"


@pytest.mark.parametrize(("pair", "service"), sorted(SHARED.items()))
def test_both_callers_reach_the_shared_service(pair, service):
    """The property the two bugs violated. Not "both call something" — both call *this*."""
    console_fn, command = pair
    assert service in _app_calls(WEBUI), f"the console no longer reaches {service}"
    assert service in _app_calls(CLI), f"the command line no longer reaches {service}"


@pytest.mark.parametrize(("pair", "service"), sorted(SHARED.items()))
def test_the_console_handler_kept_no_logic_of_its_own(pair, service):
    """An adapter that grows logic is how the two sides start to differ again. The console's
    handler should unpack a request and map one exception."""
    console_fn, _ = pair
    tree = ast.parse(WEBUI.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if getattr(n, "name", "") == console_fn)
    lines = fn.end_lineno - fn.lineno + 1
    assert lines <= 30, (
        f"{console_fn} is {lines} lines. It should unpack and translate; anything more belongs "
        "in the service, or the command line will not have it."
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

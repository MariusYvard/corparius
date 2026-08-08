"""Both ends of the command table, the last registry in the project without them.

`tests/test_registries.py` exists because nine bugs here had one shape: something produced and
never consumed, or reachable and never reached. `tests/test_route_table.py` closed that hole for
the 57 HTTP endpoints. This closes it for the 33 commands, and the two failure modes are the
same ones:

  * a `cmd_*` function no parser dispatches to is dead code with nothing to notice it — the
    shape of `documents.images()` having no caller for two releases;
  * a parser with no `fn`, or an `fn` naming a function that moved, is an `AttributeError` on
    whoever types that command first. Not in a test — in a terminal.

Neither was checkable before stage 7. `main()` was 203 lines that built the tree and parsed in
one breath, so the only way to see what was registered was to run a command; the tree existed
for the duration of one call and nothing could ask it anything. `build_parser()` is the whole
difference, and it is why the split was worth doing beyond the line count.

Two commands dispatch through a lambda — `approve` and `reject` are `cmd_decide` with the
decision bound at registration, which is right: a decision is a decision, and two parsers over
one code path is what says so. So the resolution below reads `fn.__code__.co_names` rather than
`fn.__name__`, and that is stated here rather than hidden in a helper, because a scan that
quietly skipped the lambdas would report both ends held while two commands went unchecked.
"""

import argparse
import inspect

import pytest

from corparius import cli

# The nine group modules. Named rather than discovered, for the reason every registry in this
# project is: a `glob` that stopped matching would weaken every assertion below without failing
# one, which is exactly how the flat glob in test_registries.py nearly disarmed the whole
# restructuring.
GROUPS = (
    "access",
    "lifecycle",
    "operate",
    "backlog",
    "publish",
    "configure",
    "prove",
    "maintain",
    "console",
)
# The four sub-CLIs own their own parsers and predate the pattern. Their commands are nested one
# level deeper (`corparius plugin list`), so the top level carries no `fn` — and all four make
# their subcommand required, which is what turns "no fn here" into a usage message instead of an
# AttributeError.
SUBCLI = ("plugin", "skills", "apps", "secrets")


def _parser():
    return cli.build_parser()


def _table() -> dict:
    """Every top-level command name -> the `fn` its parser dispatches to."""
    parser = _parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {name: sp.get_default("fn") for name, sp in action.choices.items()}


def _group_modules() -> dict:
    from importlib import import_module

    return {name: import_module(f"corparius.cli.{name}") for name in GROUPS}


def _defined() -> dict:
    """Every `cmd_*` a group module defines -> "module.name"."""
    out = {}
    for name, module in _group_modules().items():
        for attr, obj in vars(module).items():
            if (
                attr.startswith("cmd_")
                and inspect.isfunction(obj)
                and obj.__module__ == module.__name__
            ):
                out[f"{name}.{attr}"] = obj
    return out


def _dispatched_names() -> set[str]:
    """The `cmd_*` each registered parser really calls, lambdas resolved.

    `approve` and `reject` are `lambda a: cmd_decide(a, ...)`, so `__name__` is `<lambda>` and
    `co_names` is `('cmd_decide',)`. Reading the code object is the honest way to see through
    one; a scan that only looked at `__name__` would leave two commands unchecked while
    reporting that both ends are held.
    """
    found = set()
    for fn in _table().values():
        if fn is None:
            continue
        group = fn.__module__.rsplit(".", 1)[1]
        if fn.__name__ == "<lambda>":
            found |= {f"{group}.{n}" for n in fn.__code__.co_names}
        else:
            found.add(f"{group}.{fn.__name__}")
    return found


# --- the guard on the guard -----------------------------------------------------


def test_there_is_a_table_to_check():
    """An empty scan makes everything below vacuously true, which is the failure this file
    exists to catch one level down."""
    assert len(_table()) >= 30, f"only {len(_table())} commands registered"
    assert len(_defined()) >= 25, f"the command scan found {len(_defined())}"


def test_every_group_registers_something():
    """A group module that stopped being listed in `build_parser` would take its commands out of
    the CLI silently — the parser would simply not have them, and nothing else looks."""
    table = _table()
    for name, module in _group_modules().items():
        assert hasattr(module, "register"), f"cli/{name}.py has no register()"
        mine = {
            fn
            for fn in table.values()
            if fn is not None and fn.__module__ == f"corparius.cli.{name}"
        }
        assert mine, f"cli/{name}.py registers no command that reached the table"


# --- both ends ------------------------------------------------------------------


def test_every_command_function_is_reachable():
    """The first failure mode. A `cmd_*` nobody registered cannot be typed, and reads as a
    feature to the next person who greps for it."""
    orphans = sorted(set(_defined()) - _dispatched_names())
    assert not orphans, (
        f"these command functions are defined and no parser dispatches to them: {orphans}. "
        "Register them, or delete them."
    )


def test_every_parser_names_a_function_that_exists():
    """The mirror, and the one that bites in a terminal: `args.fn` is looked up after parsing,
    so a stale name is an AttributeError on the first person to type that command."""
    ghosts = sorted(_dispatched_names() - set(_defined()))
    assert not ghosts, f"parsers dispatch to functions no group defines: {ghosts}"


def test_every_command_has_an_fn_or_a_required_subcommand():
    """A parser with no `fn` is not a bug in itself — the four sub-CLIs are groups, not
    commands. It is a bug when nothing forces a subcommand, because then `corparius plugin`
    reaches `args.fn` and there is none. Measured: all four already require one."""
    parser = _parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, sp in action.choices.items():
        if sp.get_default("fn") is not None:
            continue
        assert name in SUBCLI, f"{name} has no fn and is not a declared sub-CLI group"
        nested = [a for a in sp._actions if isinstance(a, argparse._SubParsersAction)]
        assert nested, f"corparius {name} has neither an fn nor subcommands"
        assert all(a.required for a in nested), (
            f"corparius {name} with no subcommand would reach args.fn and find nothing"
        )


# --- what a command is ----------------------------------------------------------


@pytest.mark.parametrize("qualified", sorted(_defined()))
def test_every_command_takes_the_parsed_arguments(qualified):
    """The CLI's half of the rule `tests/test_route_table.py` states for handlers. A command is
    dispatched as `args.fn(args)`, so its first parameter is the namespace; anything else is a
    service that was left in the transport.

    `cmd_decide` takes a second parameter, bound at registration. That is the exception and it
    is visible in the table, which is the difference between an exception and a leak.
    """
    fn = _defined()[qualified]
    params = list(inspect.signature(fn).parameters)
    assert params and params[0] == "args", f"{qualified} takes {params or 'nothing'}"


def test_the_listing_order_is_the_group_order():
    """`--help` lists commands in registration order, so the order is a choice. It used to be
    accretion order — whatever was added when — which put `new`, the first command anyone types,
    twenty-fifth of twenty-nine."""
    names = list(_table())
    assert names[0] == "new", f"--help now opens with {names[0]!r}"
    # Groups stay contiguous: every module's commands are one run, not scattered.
    seen, runs = set(), []
    for name in names:
        fn = _table()[name]
        module = fn.__module__ if fn is not None else "subcli"
        if not runs or runs[-1] != module:
            assert module not in seen, f"{module} is listed in two separate runs"
            seen.add(module)
            runs.append(module)
    assert len(runs) >= 8, f"only {len(runs)} groups in the listing"

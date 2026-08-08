"""The command line. Rank 6, and nothing in the package imports this folder.

This was `cli.py`: 1 120 lines, 29 commands, and a `main()` of 203 lines that was the entire
argparse tree in one function. Split by command group, named for what the group *does*:

```text
lifecycle  init new delete repo          which companies exist
operate    run status flow board ceo     running one and asking how it is doing
backlog    tasks task approvals approve reject inbox
publish    site deploy
prove      preflight bench claude mail   a key being set is not a model answering
maintain   doctor backup restore update  acts on the install, not on a company
configure  set memory rules
console    ui
support    resolving a company, and --company
```

**Each group registers its own parsers.** That is the point of the split, not the line count: a
group is now readable end to end — the commands, their flags and their help strings in one file
— and `main()` is a loop. In the old shape a command's implementation and its flags were four
hundred lines apart, which is how `--company` came to be spelled twenty times.

It also makes the CLI a registry with **both ends held**, the way the route table now is
(`tests/test_cli_registry.py`): every `cmd_*` a group defines is reachable from the parser
table, and every parser names a `cmd_*` that exists. A command function nobody registered used
to be dead code with no way to notice, and a `set_defaults(fn=...)` left off a parser was an
`AttributeError` on whoever typed that command first.

The group imports stay **deferred**, inside `build_parser`. After the layering that is no longer
a cycle — it was `{appcli, cli, secretscli}`, dissolved by moving two lines to
`app/support.py` — it is a start-up cost choice: `corparius status` should not import the
preflight sweep or the HTTP transport. Written out explicitly rather than looked up by string,
because `tests/test_layers.py` reads imports from the AST and a dynamic `import_module` would
hide the edge from it while leaving the coupling exactly where it was.
"""

from __future__ import annotations

import argparse

from ..config.settings import setup_logging


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface, built and not run.

    Separate from `main` so it can be inspected: the registry ratchet walks `sub.choices` to
    ask each parser which function it dispatches to. When this lived inside `main` the only way
    to see the tree was to run a command.
    """
    from . import backlog, configure, console, lifecycle, maintain, operate, prove, publish

    p = argparse.ArgumentParser(prog="corparius", description="Run autonomous AI micro-companies.")
    sub = p.add_subparsers(dest="cmd", required=True)
    # The order is the order `--help` lists them, so it is chosen rather than inherited: it
    # reads like a working session. The old listing was accretion order — whatever was added
    # when — which put `new`, the first command anyone types, twenty-fifth.
    for group in (lifecycle, operate, backlog, publish, configure, prove, maintain, console):
        group.register(sub)

    # The four sub-CLIs, which own their own parsers. They register themselves for the same
    # reason the groups above do, and they predate the pattern.
    from .. import appcli, plugincli, secretscli, skillcli

    plugincli.add_parser(sub)
    skillcli.add_parser(sub)
    appcli.add_parser(sub)
    secretscli.add_parser(sub)
    return p


def main(argv=None) -> int:
    setup_logging()
    from .. import company, plugins

    plugins.load()  # no-op unless CORP_PLUGINS_ENABLED; extends the registries
    # Copy the bundled example into a fresh writable companies dir, the same
    # first-run seeding the frozen launcher does. Guarded: in a source checkout
    # the example already sits in companies/, so this is a stat and a return.
    company.seed_examples()
    args = build_parser().parse_args(argv)
    # The return value was discarded, so a command had no way to tell a shell it failed —
    # `corparius deploy` printed "no provider succeeded" and exited 0, which a script around it
    # reads as a publish. `None` still means success, so the twenty-odd commands that return
    # nothing are unaffected.
    return int(args.fn(args) or 0)

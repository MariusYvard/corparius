"""Serving the operator console. Rank 6, and one command.

Its own module rather than a line in another group, because `api/` is a whole half of the
product and `ui` is the only door to it. The import is deferred inside the command: starting a
console is the one case where loading the transport is what the operator asked for, and the
other 28 commands should not pay for it.
"""

from __future__ import annotations

from ..config.settings import Settings


def cmd_ui(args) -> None:
    from ..api import serve

    raise SystemExit(serve(Settings(), host=args.host, port=args.port))


def register(sub) -> None:
    sp = sub.add_parser("ui", help="serve the operator console")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=cmd_ui)

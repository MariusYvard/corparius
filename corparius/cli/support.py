"""Resolving a company for a command line, and the two lines every group needs. Rank 6.

`load_company` is the exit-with-a-message ergonomics and nothing else: the resolving, the
defaults and the validation are in `app/companies.load`, so the CLI, the console and the MCP
server cannot drift apart on what a company *is*.

That split is new, and it fixed something. This function used to hold the loading **and** the
`sys.exit`, and `mcp_server` imported it — so a bad company name in an MCP tool call raised
`SystemExit` inside a long-running server. A terminal should exit; a server should refuse the
call. Same knowledge, two right answers, and one of them was wrong for the caller that borrowed
it.
"""

from __future__ import annotations

import os
import sys

from .. import company
from ..app import companies as app_companies
from ..app.errors import Refused


def company_path(slug_or_path: str) -> str:
    if os.path.isfile(slug_or_path):
        return slug_or_path
    # Route through the single company resolver so the CLI, console and MCP
    # server agree on where companies live (writable home, per-OS when frozen).
    return str(company.path_for(slug_or_path))


def load_company(slug_or_path: str) -> dict:
    """`app_companies.load`, with a terminal's answer to a refusal.

    Two lines, and they are the only two that belong to this layer: a person who typed a wrong
    slug wants the sentence and a non-zero exit, not a traceback.
    """
    try:
        return app_companies.load(slug_or_path)
    except Refused as exc:
        sys.exit(str(exc))


def with_company(sp):
    """`--company`, on the twenty parsers that need one.

    A shared helper rather than twenty copies, and it lives here because `cli/__init__.py`
    hands it to nobody: each group module calls it directly, so a group can be read on its own.
    """
    sp.add_argument("--company", required=True, help="slug or path to company.yaml")
    return sp

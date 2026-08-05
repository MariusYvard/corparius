"""HTTP primitives with no server attached. Rank 0: pure, stdlib only.

Small, and load-bearing out of proportion to its size. These three lived in `webui.py`, and
`appserver.py` — a second, separate HTTP server for company apps — imported them from there.
That one import is what made the console cycle: `appserver → webui → doctor → appserver`.

A body ceiling and a Host-header parser are not console features. They are what any HTTP
server in this project needs before it can decide whether to trust a request, which is
exactly the kind of thing rank 0 is for.
"""

from __future__ import annotations

# The largest body a server accepts by default. The biggest legitimate one is a company YAML
# or a settings batch, orders of magnitude under this. Individual routes raise it (a document
# upload does) by declaring their own ceiling.
MAX_BODY = 1 << 20

# Hosts that mean "this machine". `""` is included because a Host header may be absent —
# HTTP/1.0 clients and some tools omit it — and an absent host is not evidence of a
# cross-origin request. `0.0.0.0` appears because it is what a *bind* address looks like,
# and the check that uses it compares one.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", ""})


def host_only(header: str) -> str:
    """The host from a Host header, without the port, bracket-aware for IPv6.

    A bare rsplit(":", 1) mangles a bracketed literal: "[::1]" splits on the inner colon.
    Peel the brackets first so "[::1]" and "[::1]:8600" both yield "::1", while
    "127.0.0.1:8600" and "localhost" are unchanged.

    This came from a real bug, and it is a security primitive: the DNS-rebinding defence
    compares its result against the allow-list, so a host that parses wrongly is a host that
    is checked wrongly.
    """
    raw = header.strip()
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")].lower()
    return raw.rsplit(":", 1)[0].lower()

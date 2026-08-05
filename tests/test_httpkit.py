"""The Host-header parser, tested where it now lives.

It is a security primitive: the DNS-rebinding defence compares its result against the
allow-list, so a host that parses wrongly is a host that is checked wrongly. `webui` and
`appserver` both stand on it, which is why it is in the kernel rather than in either.

`tests/test_webui_security.py` still exercises it through `webui._host_only` — deliberately,
because that re-export is what the console's own guard calls, and a test that only reached
the kernel would stop noticing if the console quietly grew a second parser.
"""

import pytest

from corparius.kernel import httpkit


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("[::1]:8600", "::1"),  # the bug: rsplit(":", 1) splits inside the literal
        ("[::1]", "::1"),
        ("[2001:db8::1]:80", "2001:db8::1"),
        ("127.0.0.1:8600", "127.0.0.1"),
        ("localhost", "localhost"),
        ("LocalHost:8600", "localhost"),  # header comparison is case-insensitive
        ("  localhost:8600  ", "localhost"),
        ("", ""),  # absent Host: HTTP/1.0 clients omit it, and that is not an attack
    ],
)
def test_the_host_is_peeled_from_the_header(header, expected):
    assert httpkit.host_only(header) == expected


def test_an_absent_host_reads_as_loopback_rather_than_as_a_stranger():
    """`""` is in LOOPBACK on purpose. A missing Host header is not evidence of a
    cross-origin request, and treating it as one would refuse curl and every HTTP/1.0
    client for no gain."""
    assert httpkit.host_only("") in httpkit.LOOPBACK


def test_a_public_host_is_not_loopback():
    assert httpkit.host_only("evil.example:8600") not in httpkit.LOOPBACK


def test_both_servers_read_the_same_definitions():
    """The point of the module. `appserver` used to import these from `webui`, which is the
    whole of what made the two a cycle — and a second copy of a security primitive is how
    the two guards come to disagree."""
    from corparius import appserver, webui

    assert webui.MAX_BODY is httpkit.MAX_BODY
    assert webui._host_only is httpkit.host_only
    assert appserver.host_only is httpkit.host_only
    assert appserver.MAX_BODY is httpkit.MAX_BODY

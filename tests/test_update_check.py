"""The opt-in version check must stay silent unless the operator turns it on:
the project's rule is no unconsented network call in the shipped product."""

import pytest

from app import update_check


def _boom(*a, **k):
    raise AssertionError("network was contacted while the check was disabled")


def test_disabled_makes_no_network_call(monkeypatch):
    monkeypatch.delenv("CORP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update_check, "urlopen", _boom)
    result = update_check.check()
    assert result == {"enabled": False, "current": update_check.current_version()}


def test_enabled_reports_newer_version(monkeypatch):
    monkeypatch.setenv("CORP_UPDATE_CHECK", "true")
    monkeypatch.setattr(update_check, "latest", lambda timeout=4.0: "v999.0.0")
    result = update_check.check()
    assert result["enabled"] is True
    assert result["update_available"] is True
    assert result["latest"] == "999.0.0"
    assert result["url"] == update_check.RELEASES_URL


def test_enabled_no_update_when_same_version(monkeypatch):
    monkeypatch.setenv("CORP_UPDATE_CHECK", "true")
    monkeypatch.setattr(
        update_check, "latest", lambda timeout=4.0: "v" + update_check.current_version()
    )
    assert update_check.check()["update_available"] is False


def test_enabled_but_unreachable(monkeypatch):
    monkeypatch.setenv("CORP_UPDATE_CHECK", "true")
    monkeypatch.setattr(update_check, "latest", lambda timeout=4.0: None)
    result = update_check.check()
    assert result == {
        "enabled": True,
        "reachable": False,
        "current": update_check.current_version(),
    }


@pytest.mark.parametrize(
    "a,b,newer",
    [
        ("v0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("v0.1.0", "0.2.0", False),
        ("v1.0.0", "0.9.9", True),
    ],
)
def test_parse_ordering(a, b, newer):
    assert (update_check._parse(a) > update_check._parse(b)) is newer

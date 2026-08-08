"""`corparius preflight`: what it says before it spends, and what it refuses to claim.

The second file the stage-7 coverage ratchet asked for. `cli/prove.py` came out of the split at
**50.0%** — 91 untested statements, almost all of them `cmd_preflight`, which is the one command
in the product whose whole purpose is to make real calls on the operator's own account.

`tests/test_preflight.py` covers the prober. What was untested is the command around it, and
every property below is about one of two things:

  * **the price is stated before anything runs**, and `--yes` is the only way past it. The same
    invariant `restore` and `update` have (`tests/test_maintain_commands.py`), for the same
    reason: a terminal has no confirm dialog, so the printed sentence *is* the dialog.
  * **it never claims knowledge it does not have.** This command exists because `/models` lists
    models an account cannot call — 8 of 14 sampled NVIDIA entries answered 404 for a real key.
    A version of it that said "remembered" after calling nothing would reintroduce exactly the
    lie it was written to end, and the code says so in a comment. That comment is now a test.

`exit(1)` throughout is not decoration. This is a command people put in a cron job or run over
SSH before trusting a routing change; "nothing was called" and "everything works" have to be
distinguishable without reading the prose.
"""

import types

import pytest

from corparius.cli import prove
from corparius.providers import preflight


def _args(**kw):
    base = {
        "json": False,
        "timeout": 5,
        "provider": "",
        "limit": 20,
        "all": False,
        "yes": False,
        "quick": True,
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


def _never(name):
    def boom(*a, **k):
        raise AssertionError(f"{name} was called and must not have been")

    return boom


@pytest.fixture(autouse=True)
def _a_real_looking_install(tmp_path, monkeypatch):
    """Out of mock mode and into a private store, because the first thing the command does is
    refuse to run in mock mode — which is the right answer and would make every other test here
    exercise that one branch."""
    from corparius.config import cfg

    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    monkeypatch.setenv("CORP_LLM_MOCK", "false")
    cfg.invalidate()


def _probe(state, model="m", provider="groq", status=200):
    return preflight.Probe(
        provider=provider, model=model, tier="hard", state=state, detail="d", status=status
    )


# --- mock mode ------------------------------------------------------------------


def test_mock_mode_is_refused_rather_than_faked(monkeypatch):
    """Mock mode is a real capability — it is how the product runs offline on a first install —
    but there is no provider in it, so there is nothing to prove. Exit 1, because a script that
    ran this to check its routing did not get an answer."""
    from corparius.config import cfg

    monkeypatch.setenv("CORP_LLM_MOCK", "true")
    cfg.invalidate()
    monkeypatch.setattr(preflight, "run", _never("preflight.run"))
    monkeypatch.setattr(preflight, "sweep", _never("preflight.sweep"))
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args())
    assert exc.value.code == 1


# --- the price gate -------------------------------------------------------------


def test_all_states_the_price_and_runs_nothing_without_yes(monkeypatch, capsys):
    """The console has a confirm dialog for "Check every model"; a terminal has this sentence.

    `sweep` fails the test if reached, so the assertion is the property and not the wording.
    """
    monkeypatch.setattr(
        preflight, "estimate", lambda: {"total": 147, "providers": {"groq": 100, "cerebras": 47}}
    )
    monkeypatch.setattr(preflight, "sweep", _never("preflight.sweep"))
    assert prove.cmd_preflight(_args(all=True)) is None
    out = capsys.readouterr().out
    assert "147 model(s)" in out and "2 provider(s)" in out
    assert "groq" in out and "cerebras" in out
    assert "real generation on your own account" in out
    assert "--yes" in out, "the way past the gate has to be named in the gate"


def test_all_with_nothing_configured_refuses_instead_of_reporting_zero(monkeypatch, capsys):
    """A sweep of nothing is not a successful sweep. Exit 1 and name the fix."""
    monkeypatch.setattr(preflight, "estimate", lambda: {"total": 0, "providers": {}})
    monkeypatch.setattr(preflight, "sweep", _never("preflight.sweep"))
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args(all=True))
    assert exc.value.code == 1
    assert "Set a provider key first" in capsys.readouterr().out


def test_all_with_yes_sweeps_and_says_it_was_remembered(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "estimate", lambda: {"total": 2, "providers": {"groq": 2}})
    seen = {}
    monkeypatch.setattr(
        preflight,
        "sweep",
        lambda store, limit, timeout: (
            seen.setdefault("limit", limit) or {"probed": 2, "counts": {"usable": 2}}
        ),
    )
    assert prove.cmd_preflight(_args(all=True, yes=True, limit=0)) is None
    out = capsys.readouterr().out
    assert "2 called" in out and "Remembered" in out
    assert seen["limit"] == 0, "--limit 0 means all, and it has to reach the sweep as 0"


# --- never claim what was not learned -------------------------------------------


def test_a_provider_with_no_catalogue_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "probe_catalogue", lambda *a, **k: [])
    monkeypatch.setattr(preflight, "remember", _never("preflight.remember"))
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args(provider="nvidia"))
    assert exc.value.code == 1
    assert "nothing to try" in capsys.readouterr().out


def test_probes_that_never_reached_the_network_are_not_called_remembered(monkeypatch, capsys):
    """The honesty invariant, and the code comments it verbatim: "Saying 'remembered' here would
    claim knowledge that does not exist, which is the failure this whole command exists to end."

    `status == 0` means nothing answered — no key, or the endpoint never replied. The verdicts
    are still stored (they are what was observed), but the summary must not tell an operator the
    catalogue was proven.
    """
    probes = [
        _probe(preflight.UNKNOWN, model="a", status=0),
        _probe(preflight.UNKNOWN, "b", status=0),
    ]
    monkeypatch.setattr(preflight, "probe_catalogue", lambda *a, **k: probes)
    monkeypatch.setattr(preflight, "remember", lambda *a, **k: None)
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args(provider="nvidia"))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Nothing was called, so nothing was learned" in out
    assert "Remembered for" not in out


def test_a_provider_sweep_that_did_reach_the_network_reports_the_three_verdicts(
    monkeypatch, capsys
):
    """usable / not callable / cold, counted separately — because a 429 is not evidence against
    a model and merging it into "failed" is how free tiers get thrown away."""
    probes = [
        _probe(preflight.USABLE, "a"),
        _probe(preflight.BLOCKED, "b", status=404),
        _probe(preflight.CAPACITY, "c", status=429),
    ]
    monkeypatch.setattr(preflight, "probe_catalogue", lambda *a, **k: probes)
    monkeypatch.setattr(preflight, "remember", lambda *a, **k: None)
    assert prove.cmd_preflight(_args(provider="nvidia")) is None
    out = capsys.readouterr().out
    assert "1 usable, 1 not callable with this key, 1 cold or unclear, of 3 tried" in out
    assert "Remembered for nvidia" in out


# --- the tier path --------------------------------------------------------------


def _no_catalogue_refresh(monkeypatch):
    from corparius.providers import modelinfo

    monkeypatch.setattr(modelinfo, "refresh", lambda _store: {})
    monkeypatch.setattr(modelinfo, "cached", lambda _store: {})


def test_no_tier_pointing_at_a_provider_is_refused(monkeypatch, capsys):
    _no_catalogue_refresh(monkeypatch)
    monkeypatch.setattr(preflight, "targets", lambda _s: [])
    monkeypatch.setattr(preflight, "run", _never("preflight.run"))
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args())
    assert exc.value.code == 1
    assert "nothing to call" in capsys.readouterr().out


def _a_report(monkeypatch, probes):
    _no_catalogue_refresh(monkeypatch)
    monkeypatch.setattr(preflight, "targets", lambda _s: [("hard", "groq:m")])
    monkeypatch.setattr(preflight, "run", lambda _s, timeout: preflight.Report(probes=probes))
    monkeypatch.setattr(preflight, "save", lambda *a, **k: None)


def test_a_blocked_model_makes_the_command_fail(monkeypatch, capsys):
    """The distinction a cron job depends on. A configured tier that cannot be called is a
    misconfiguration an operator has to act on, so it is a non-zero exit."""
    _a_report(
        monkeypatch, [_probe(preflight.USABLE, "a"), _probe(preflight.BLOCKED, "b", status=404)]
    )
    with pytest.raises(SystemExit) as exc:
        prove.cmd_preflight(_args())
    assert exc.value.code == 1
    assert "cannot be called with this key" in capsys.readouterr().out


def test_a_rate_limited_model_alone_does_not_make_it_fail(monkeypatch, capsys):
    """ "That is capacity, not a verdict." The free tiers this project is built for look exactly
    like this when they wake up, and exiting non-zero would teach an operator to ignore the
    exit code — after which the blocked case above says nothing either."""
    _a_report(
        monkeypatch, [_probe(preflight.USABLE, "a"), _probe(preflight.CAPACITY, "c", status=429)]
    )
    assert prove.cmd_preflight(_args()) is None
    out = capsys.readouterr().out
    assert "capacity, not a verdict" in out
    assert "run this again in a minute" in out


def test_json_output_is_the_report_and_not_the_prose(monkeypatch, capsys):
    """`--json` is for a script, so it gets `report.as_dict()` and none of the lines a person
    reads — a mixed stream is not parseable and a caller would have to guess where it starts."""
    import json as json_mod

    _a_report(monkeypatch, [_probe(preflight.USABLE, "a")])
    prove.cmd_preflight(_args(json=True))
    out = capsys.readouterr().out
    payload = out[out.index("{") :]
    parsed = json_mod.loads(payload)
    assert [p["model"] for p in parsed["probes"]] == ["a"]
    assert "[usable " not in out, "the human table must not be printed alongside the JSON"

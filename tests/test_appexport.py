"""Exporting an app to a function deployed with the site.

This is the one path where corparius hands something away: once the key sits at
the host, the daily ceiling, the rate limit and the cost breakdown stop
applying. So the tests are about saying so, and about refusing the exports that
could only fail later — a `local:` tier has no Ollama in a serverless function,
and an app with no origins would refuse every browser it was written for.

The generated file is JavaScript, which nothing else in this repo type-checks
or runs. `node --check` does, when node is around.
"""

import json
import shutil
import subprocess

import pytest

from corparius import appexport, apps
from corparius.config.settings import Settings
from corparius.kernel.records import Difficulty

APP = apps.App(
    name="faq",
    system='Answer questions. Never invent a "price".',
    tier=Difficulty.TRIVIAL,
    max_tokens=300,
    origins=["https://site.test"],
)


def _settings(monkeypatch, trivial="groq:llama-3.3-70b-versatile"):
    from corparius import cfg

    monkeypatch.setenv("CORP_TRIVIAL_MODEL", trivial)
    cfg.invalidate()
    return Settings()


def test_the_plan_follows_the_tier_the_app_already_declares(monkeypatch):
    """One tier, resolved the same way the endpoint resolves it, so an export
    calls the model the app was tried against."""
    target = appexport.plan(APP, _settings(monkeypatch))
    assert target["provider"] == "groq"
    assert target["model"] == "llama-3.3-70b-versatile"
    assert target["endpoint"] == "https://api.groq.com/openai/v1"
    assert target["key_env"] == "GROQ_API_KEY"


@pytest.mark.parametrize("tier", ["local:gemma:2b", "claudecode:haiku", "cloud:sonnet"])
def test_a_tier_that_cannot_exist_in_a_function_is_refused(monkeypatch, tier):
    """Local needs Ollama on the host, claudecode needs the CLI and its login,
    and cloud is the Anthropic key you would then be copying out. Refusing now
    beats a config that fails on the first visitor."""
    with pytest.raises(appexport.ExportError) as exc:
        appexport.plan(APP, _settings(monkeypatch, tier))
    assert tier.split(":")[0] in str(exc.value)


def test_an_app_with_no_origins_is_refused(monkeypatch):
    """The function would refuse every browser it exists for, and the operator
    would debug a CORS error instead of reading one sentence here."""
    bare = apps.App(name="faq", system="s", origins=[])
    with pytest.raises(appexport.ExportError, match="origins"):
        appexport.plan(bare, _settings(monkeypatch))


def test_the_generated_file_says_what_was_given_up(monkeypatch):
    """At the top, in the file the operator is reading while they give it up."""
    body = appexport.render(APP, appexport.plan(APP, _settings(monkeypatch)))
    # Unwrapped: the warning is a comment block, so its sentences are split
    # across lines by "// ".
    head = " ".join(body[: body.index("const SYSTEM")].replace("//", " ").split())
    assert "corparius no longer sees these calls" in head
    assert "ceiling" in head and "rate limit" in head
    assert "GROQ_API_KEY" in head


def test_the_prompt_is_embedded_as_json_not_pasted(monkeypatch):
    """A system prompt with a quote or a newline in it would otherwise produce
    a file that does not parse — which is exactly what a system prompt has."""
    body = appexport.render(APP, appexport.plan(APP, _settings(monkeypatch)))
    assert json.dumps(APP.system) in body
    assert json.dumps(APP.origins) in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_generated_function_parses(monkeypatch, tmp_path):
    """Generated JavaScript is checked by nothing else here: no linter, no type
    checker, no import. `node --check` is the only thing standing between a
    template typo and a site that 500s on its first visitor."""
    body = appexport.render(APP, appexport.plan(APP, _settings(monkeypatch)))
    path = tmp_path / "faq.mjs"
    path.write_text(body, encoding="utf-8")
    proc = subprocess.run(
        [shutil.which("node"), "--check", str(path)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_the_export_writes_beside_the_site_and_refuses_to_overwrite(tmp_path, monkeypatch):
    import yaml

    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    d = tmp_path / "companies" / "t" / "apps"
    d.mkdir(parents=True)
    (d / "faq.yaml").write_text(
        yaml.safe_dump(
            {"name": "faq", "system": "s", "origins": ["https://site.test"], "max_tokens": 300}
        ),
        encoding="utf-8",
    )
    settings = _settings(monkeypatch)
    out = tmp_path / "site"
    done = appexport.export("t", "faq", out, settings)
    assert done["path"].endswith("faq.mjs")
    assert (out / "netlify" / "functions" / "faq.mjs").is_file()

    # An exported function is a file the operator may have edited.
    with pytest.raises(appexport.ExportError, match="already exists"):
        appexport.export("t", "faq", out, settings)


def test_exporting_an_app_that_does_not_exist_is_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    with pytest.raises(appexport.ExportError, match="no app named"):
        appexport.export("t", "absent", tmp_path / "site", _settings(monkeypatch))

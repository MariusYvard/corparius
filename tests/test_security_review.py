"""Two holes an adversarial review found, and the tests that keep them shut.

Both were deviations from controls this project had deliberately built — which
is what made them worth reporting and worth pinning. Neither was theoretical:
each was reproduced against the real code before it was fixed.
"""

import ast
import pathlib

import pytest

from corparius import backup, selfupdate, webui

# --- 1. the update tag walked out of the repository ------------------------


def test_a_tag_cannot_walk_the_download_url_into_another_repository():
    """`requests` normalises dot segments while preparing a request, so
    DOWNLOAD_BASE pinned nothing: `../../../../someone/else/releases/download/v1`
    resolved to their repo. The checksum was no defence — SHA256SUMS came from
    the same redirected directory, so the verification agreed with itself, and
    the binary was installed and then run.
    """
    import requests

    hostile = "../../../../attacker/evil/releases/download/v1"
    prepared = requests.Request(
        "GET", f"{selfupdate.DOWNLOAD_BASE}/{hostile}/{selfupdate.SUMS}"
    ).prepare()
    assert "attacker/evil" in prepared.url, "this is why the guard exists"

    with pytest.raises(selfupdate.UpdateError, match="not a release tag"):
        selfupdate.check_tag(hostile)


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../attacker/evil/releases/download/v1",
        "v0.1.0/../../..",
        "v1;rm -rf /",
        "..%2f..%2fevil",
        "https://evil.example/x",
        "latest",
        "",
        "   ",
    ],
)
def test_only_a_version_reaches_the_download_url(hostile):
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.check_tag(hostile)


@pytest.mark.parametrize("good", ["v0.1.0", "0.1.0", "v1", "v1.2.3.4"])
def test_a_real_release_tag_is_accepted(good):
    assert selfupdate.check_tag(good) == good


def test_the_console_never_takes_the_tag_from_the_request(monkeypatch):
    """The fix that matters. The guard above is the second lock; this is the
    first — the console asks the version check, exactly as the CLI always did.
    """
    from corparius import update_check

    seen = {}
    monkeypatch.setattr(
        update_check,
        "check",
        lambda *a, **k: {"enabled": True, "update_available": True, "latest": "0.2.0"},
    )
    monkeypatch.setattr(
        selfupdate, "apply", lambda tag: seen.setdefault("tag", tag) or {"ok": True, "backup": ""}
    )
    ctx = type("Ctx", (), {"body": {"tag": "../../../../attacker/evil/releases/download/v1"}})()
    status, _payload = webui._route_update_apply(ctx)
    assert status == 200
    assert seen["tag"] == "v0.2.0", "the body's tag reached the downloader"


# --- 2. a line break in a value wrote settings of its own ------------------


def _env(tmp: pathlib.Path) -> pathlib.Path:
    path = tmp / ".env"
    path.write_text("CORP_LLM_MOCK=true\n", encoding="utf-8")
    return path


def test_a_line_break_in_a_value_cannot_append_a_setting(tmp_path):
    """Values were written verbatim and joined with newlines, so one accepted
    write could append lines of its own. The line worth appending was
    CORP_UI_ALLOWED_HOSTS — which SECURITY.md promises cannot be set through
    the API, and which a test asserts is absent from ALLOWED_VARS. The name was
    absent; the value was not.
    """
    path = _env(tmp_path)
    hostile = "p4ss\nCORP_UI_ALLOWED_HOSTS=evil.example\nCORP_PLUGINS_ALLOW_UNVERIFIED=true"
    with pytest.raises(webui._RequestRefused) as refused:
        webui._merge_env_file(path, {"CORP_SECRET_KEY": hostile})
    assert refused.value.status == 400
    got = path.read_text(encoding="utf-8")
    assert "CORP_UI_ALLOWED_HOSTS" not in got
    assert "CORP_PLUGINS_ALLOW_UNVERIFIED" not in got


def test_a_carriage_return_is_refused_too(tmp_path):
    """Same primitive, different byte."""
    path = _env(tmp_path)
    with pytest.raises(webui._RequestRefused):
        webui._merge_env_file(path, {"CORP_UI_TOKEN": "t\rCORP_UI_ALLOWED_HOSTS=evil.example"})
    assert "evil.example" not in path.read_text(encoding="utf-8")


def test_the_refusal_names_the_field_so_it_is_fixable(tmp_path):
    path = _env(tmp_path)
    with pytest.raises(webui._RequestRefused, match="CORP_UI_TOKEN"):
        webui._merge_env_file(path, {"CORP_UI_TOKEN": "a\nb"})


def test_an_ordinary_value_still_writes(tmp_path):
    path = _env(tmp_path)
    webui._merge_env_file(path, {"CORP_UI_TOKEN": "a-perfectly-normal-token"})
    assert "CORP_UI_TOKEN=a-perfectly-normal-token" in path.read_text(encoding="utf-8")


def test_a_crafted_archive_cannot_write_a_setting_through_a_restore(tmp_path, monkeypatch):
    """The third way into the same writer: .env comes out of a zip someone else
    may have built, and a restore merges it. The boundary drops anything that
    is not a plain KEY, and the writer refuses line breaks regardless."""
    from corparius import paths

    env = tmp_path / ".env"
    env.write_text("CORP_LLM_MOCK=true\n", encoding="utf-8")
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    backup._merge_restored_env(
        "CORP_LLM_MOCK=false\n"
        "CORP_UI_ALLOWED HOSTS=evil.example\n"  # not a key: dropped
        "  weird key with spaces  =x\n"
    )
    got = env.read_text(encoding="utf-8")
    assert "CORP_LLM_MOCK=false" in got, "the legitimate line still applies"
    assert "evil.example" not in got
    assert "weird key" not in got


def test_the_host_allow_list_is_still_not_settable_by_name():
    """The original invariant, unchanged: it protects the surface it is reached
    through, so it cannot be written through that surface."""
    assert "CORP_UI_ALLOWED_HOSTS" not in webui.ALLOWED_VARS


# Every module allowed to write a .env, and what for. A new name here is a new way into the
# file that holds CORP_UI_ALLOWED_HOSTS, so adding one should cost a line in this list.
DOTENV_CALLERS = {
    "corparius/webui.py",  # the settings page and the providers panel
    "corparius/backup.py",  # a restore, from an archive someone else may have built
    "corparius/secretscli.py",  # `corparius secrets on`
}


def test_the_writer_is_the_choke_point_every_caller_goes_through():
    """Four callers, one guard: the settings page, the providers panel, a restore, and the
    secrets CLI. Putting the check in any one of them would have left the others.

    This counted occurrences of `_merge_env_file(` in two files, which stopped meaning
    anything once the writer moved to `kernel/dotenv.py`. It now asks the question the old
    version was a proxy for: **is there exactly one function in the package that writes a
    .env, and does it refuse a line break?** Anything else appending to a dotenv path —
    including a well-meaning helper that skips the check — fails here.
    """
    callers, direct = set(), set()
    for path in sorted(pathlib.Path("corparius").rglob("*.py")):
        name = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if name != "corparius/kernel/dotenv.py" and node.func.attr in (
                "merge",
                "merge_into",
                "_merge_env_file",
            ):
                callers.add(name)
            # Anyone reaching a dotenv path with a raw write is going round the guard.
            if node.func.attr in ("write_text", "writelines", "open"):
                receiver = ast.unparse(node.func.value)
                if "env_file" in receiver or "dotenv" in receiver:
                    direct.add(f"{name}: {receiver}.{node.func.attr}()")
    assert callers == DOTENV_CALLERS, (
        f"the set of modules writing .env changed: {sorted(callers)}. Every one of them "
        "must go through kernel.dotenv, which is where the line-break refusal lives."
    )
    assert not direct, f"a .env is written without passing the guard: {sorted(direct)}"
    source = pathlib.Path("corparius/kernel/dotenv.py").read_text(encoding="utf-8")
    assert 'if "\\n" in str(v) or "\\r" in str(v)' in source, "the guard left the only writer"

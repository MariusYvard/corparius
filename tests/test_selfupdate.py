"""Replacing the binary, without ever being able to take a company with it.

The first test is the one that matters: a real update runs over a home holding
companies, a store and skills, and every byte of it has to be identical
afterwards. The rest are the refusals — a bad checksum, a build that is not the
downloadable one, a data folder in the line of fire, and a swap that fails
halfway and has to put the operator back where they started.

Losing a binary is a re-download. Losing a company is not, which is why the
failure paths here outnumber the success one four to one.
"""

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from corparius import selfupdate

NEW_BUILD = b"#!/pretend/this/is/a/binary\n" + b"x" * 4096

# Captured before any fixture stubs it, so one test can exercise the real one.
REAL_BACKUP = selfupdate._backup


def _sums(*pairs) -> str:
    return "\n".join(f"{hashlib.sha256(blob).hexdigest()}  {name}" for name, blob in pairs) + "\n"


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """A pretend installation: an executable in one folder, data in another —
    the layout paths.py produces on every OS."""
    binary = tmp_path / "app" / "corparius.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"the build that is running")
    home = tmp_path / "data"
    (home / "companies" / "acme").mkdir(parents=True)
    (home / "companies" / "acme" / "company.yaml").write_text("slug: acme\nname: Acme\n", "utf-8")
    (home / "companies" / "acme" / "leads.csv").write_text("email\na@b.c\n", "utf-8")
    (home / "data").mkdir()
    (home / "data" / "corparius.sqlite").write_bytes(b"a store with a year of work in it")

    monkeypatch.setattr(selfupdate.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(selfupdate.paths, "user_home", lambda: home)
    monkeypatch.setattr(selfupdate, "_data_path", lambda: str(home / "data"))
    monkeypatch.setattr(selfupdate, "target", lambda: binary)
    monkeypatch.setattr(selfupdate, "asset_name", lambda: "corparius-windows-x64.exe")
    monkeypatch.setattr(selfupdate, "_backup", lambda: "")
    return {"binary": binary, "home": home}


def _serve(monkeypatch, asset=NEW_BUILD, name="corparius-windows-x64.exe", sums=None):
    body = sums if sums is not None else _sums((name, asset))

    def fake_get(url: str) -> bytes:
        return body.encode("utf-8") if url.endswith(selfupdate.SUMS) else asset

    monkeypatch.setattr(selfupdate, "_get", fake_get)


def _snapshot(root: Path) -> dict:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


# --- the one that matters -------------------------------------------------


def test_an_update_does_not_touch_a_single_byte_of_company_data(frozen, monkeypatch):
    """Companies are usually the only copy of a business someone is running.
    The executable and the data live in different folders by design, and this
    proves the design holds when the code actually runs, not just on paper."""
    _serve(monkeypatch)
    before = _snapshot(frozen["home"])
    assert before, "the fixture must have written data for this to mean anything"

    selfupdate.apply("v9.9.9")

    assert _snapshot(frozen["home"]) == before
    assert frozen["binary"].read_bytes() == NEW_BUILD, "and the binary was replaced"


def test_the_build_that_was_running_is_kept_not_deleted(frozen, monkeypatch):
    """Until the new one starts, the old one is the way back."""
    _serve(monkeypatch)
    out = selfupdate.apply("v9.9.9")
    kept = Path(out["previous"])
    assert kept.read_bytes() == b"the build that is running"
    assert kept.name.endswith(selfupdate.OLD_SUFFIX)


def test_a_backup_is_taken_before_anything_moves(frozen, monkeypatch):
    """Insurance against a mistake in this file, not against a known risk. The
    order is what makes it insurance: taken while the old build is still in
    place, so a failure later leaves both the backup and the old binary."""
    order = []
    _serve(monkeypatch)
    monkeypatch.setattr(selfupdate, "_backup", lambda: order.append("backup") or "/tmp/b.zip")
    real_replace = selfupdate.os.replace
    monkeypatch.setattr(
        selfupdate.os, "replace", lambda a, b: order.append("move") or real_replace(a, b)
    )
    out = selfupdate.apply("v9.9.9")
    assert order[0] == "backup" and "move" in order
    assert out["backup"] == "/tmp/b.zip"


def test_a_backup_that_fails_does_not_stop_the_update(frozen, monkeypatch):
    """Refusing to update because a zip could not be written would trade a real
    problem for a hypothetical one. _backup swallows it and returns ""."""
    _serve(monkeypatch)
    monkeypatch.setattr(selfupdate, "_backup", REAL_BACKUP)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("corparius.backup.make_backup", boom)
    monkeypatch.setattr(selfupdate, "_data_path", lambda: "nowhere")
    out = selfupdate.apply("v9.9.9")
    assert out["ok"] is True and out["backup"] == ""


# --- the refusals ----------------------------------------------------------


def test_a_checksum_mismatch_installs_nothing(frozen, monkeypatch):
    """The whole point of the download step. A warning here would be a way to
    run whatever the network handed over."""
    _serve(monkeypatch, sums=_sums(("corparius-windows-x64.exe", b"a different build")))
    with pytest.raises(selfupdate.UpdateError, match="checksum mismatch"):
        selfupdate.apply("v9.9.9")
    assert frozen["binary"].read_bytes() == b"the build that is running"
    assert not (frozen["binary"].parent / (frozen["binary"].name + ".new")).exists()


def test_an_asset_with_no_published_sum_is_refused(frozen, monkeypatch):
    """An asset nobody published a sum for is an asset nobody vouched for."""
    _serve(monkeypatch, sums=_sums(("corparius-linux-x64", NEW_BUILD)))
    with pytest.raises(selfupdate.UpdateError, match="no line for"):
        selfupdate.apply("v9.9.9")
    assert frozen["binary"].read_bytes() == b"the build that is running"


def test_a_source_checkout_is_told_what_to_do_instead(monkeypatch):
    monkeypatch.setattr(selfupdate.paths, "is_frozen", lambda: False)
    why = selfupdate.why_not()
    assert "git pull" in why and "docker pull" in why
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.apply("v9.9.9")


def test_an_unpublished_platform_is_refused_rather_than_guessed(monkeypatch):
    monkeypatch.setattr(selfupdate.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(selfupdate, "asset_name", lambda: None)
    assert "no release is published" in selfupdate.why_not()


def test_a_binary_holding_the_data_folder_refuses_outright(tmp_path, monkeypatch):
    """A macOS bundle is a directory, and the swap moves and deletes
    directories. If someone's home ended up inside it, replacing the binary
    would take the companies with it. It should never happen; it is refused
    anyway."""
    bundle = tmp_path / "corparius.app"
    home = bundle / "data"
    home.mkdir(parents=True)
    monkeypatch.setattr(selfupdate.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(selfupdate, "asset_name", lambda: "corparius-macos-arm64.zip")
    monkeypatch.setattr(selfupdate, "target", lambda: bundle)
    monkeypatch.setattr(selfupdate.paths, "user_home", lambda: home)
    monkeypatch.setattr(selfupdate, "_data_path", lambda: str(home))
    why = selfupdate.why_not()
    assert "inside" in why and "Nothing was touched" in why


def test_a_failed_swap_puts_the_old_build_back(frozen, monkeypatch):
    """The window where no corparius exists is two renames wide. If the second
    one fails, the first is undone."""
    _serve(monkeypatch)
    real_replace = selfupdate.os.replace
    calls = []

    def flaky(a, b):
        calls.append((a, b))
        if len(calls) == 2:  # staged -> live
            raise OSError("interrupted")
        return real_replace(a, b)

    monkeypatch.setattr(selfupdate.os, "replace", flaky)
    with pytest.raises(selfupdate.UpdateError, match="old one is back"):
        selfupdate.apply("v9.9.9")
    assert frozen["binary"].read_bytes() == b"the build that is running"


def test_the_new_build_is_staged_beside_the_old_one_before_any_rename(frozen, monkeypatch):
    """Downloading and writing while the old build is still in place is what
    keeps the dangerous window to two syscalls."""
    _serve(monkeypatch)
    seen = {}
    real_replace = selfupdate.os.replace

    def watch(a, b):
        # Only on the first rename: after it, the live name is gone by design,
        # and setdefault would still evaluate the read and blow up.
        if "live_at_first_rename" not in seen:
            seen["live_at_first_rename"] = frozen["binary"].read_bytes()
            staged = frozen["binary"].parent / (frozen["binary"].name + selfupdate.NEW_SUFFIX)
            seen["staged_exists"] = staged.is_file()
        return real_replace(a, b)

    monkeypatch.setattr(selfupdate.os, "replace", watch)
    selfupdate.apply("v9.9.9")
    assert seen["live_at_first_rename"] == b"the build that is running"
    assert seen["staged_exists"] is True


# --- housekeeping ----------------------------------------------------------


def test_the_sweep_only_ever_removes_those_two_names(frozen, monkeypatch):
    """It runs at startup, next to whatever the operator keeps beside the
    program."""
    folder = frozen["binary"].parent
    (folder / "corparius.exe.old").write_bytes(b"previous")
    (folder / "corparius.exe.new").write_bytes(b"half-staged")
    (folder / "notes.txt").write_text("mine", "utf-8")
    (folder / "corparius.exe.olderly").write_text("not ours", "utf-8")

    selfupdate.sweep_previous()

    assert not (folder / "corparius.exe.old").exists()
    assert not (folder / "corparius.exe.new").exists()
    assert (folder / "notes.txt").exists()
    assert (folder / "corparius.exe.olderly").exists()
    assert frozen["binary"].exists()


def test_the_sweep_does_nothing_from_source(monkeypatch, tmp_path):
    monkeypatch.setattr(selfupdate.paths, "is_frozen", lambda: False)

    def explode():
        raise AssertionError("the sweep looked for a binary to clean up from source")

    monkeypatch.setattr(selfupdate, "target", explode)
    selfupdate.sweep_previous()


def test_a_macos_zip_yields_the_bundle_not_the_zip(tmp_path):
    """The asset is an archive; what has to land is the .app inside it."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("corparius.app/Contents/MacOS/corparius", "binary")
        zf.writestr("corparius.app/Contents/Info.plist", "<plist/>")
    destination = tmp_path / "corparius.app"
    selfupdate._write_payload(buf.getvalue(), "corparius-macos-arm64.zip", destination)
    assert (destination / "Contents" / "MacOS" / "corparius").read_text() == "binary"


def test_an_archive_without_a_bundle_is_refused(tmp_path):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not an app")
    with pytest.raises(selfupdate.UpdateError, match="no .app bundle"):
        selfupdate._write_payload(buf.getvalue(), "x.zip", tmp_path / "corparius.app")


def test_the_asset_is_named_from_the_machine_it_runs_on(monkeypatch):
    """An operator who copied a Windows build onto a Mac gets a refusal, not a
    download of the wrong file."""
    monkeypatch.setattr(selfupdate.sys, "platform", "darwin")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "arm64")
    assert selfupdate.asset_name() == "corparius-macos-arm64.zip"
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "x86_64")
    assert selfupdate.asset_name() == "corparius-macos-x64.zip"
    monkeypatch.setattr(selfupdate.sys, "platform", "win32")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "ARM64")
    assert selfupdate.asset_name() is None, "we publish no Windows arm64 build"


def test_the_providers_stay_connected_across_an_update(frozen, monkeypatch):
    """Keys and tiers live on two layers — `.env` in the home, and the settings
    table in the store — and both are in the data folder, not beside the binary.
    An operator who has connected providers should not have to reconnect them,
    and should certainly not discover that at the next tick."""
    from corparius.config import cfg
    from corparius.store import Store

    home = frozen["home"]
    (home / ".env").write_text(
        "CORP_LLM_MOCK=false\nCORP_CLOUD_ENABLED=true\n"
        "OPENROUTER_API_KEY=sk-or-test\nCORP_TRIVIAL_MODEL=openrouter:free-model\n",
        encoding="utf-8",
    )
    # The fixture writes a placeholder there; this test needs a real database.
    (home / "data" / "corparius.sqlite").unlink()
    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", "gsk-saved-from-the-console")
    store.set_setting("CORP_HARD_MODEL", "groq:llama")
    store.close()

    def resolve():
        cfg.set_dotenv_path(home / ".env")
        cfg.invalidate()
        from corparius.providers.llm import connected_providers

        return {
            "providers": sorted(connected_providers()),
            "trivial": cfg.get("CORP_TRIVIAL_MODEL"),
            "hard": cfg.get("CORP_HARD_MODEL"),
            "env_key": cfg.get("OPENROUTER_API_KEY"),
            "store_key": cfg.get("GROQ_API_KEY"),
        }

    monkeypatch.setenv("CORP_DATA_PATH", str(home / "data"))
    before = resolve()
    assert "groq" in before["providers"] and "openrouter" in before["providers"]

    _serve(monkeypatch)
    selfupdate.apply("v9.9.9")

    assert resolve() == before

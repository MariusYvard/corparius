"""What CORP_SECRET_KEY buys, and putting a backup back.

Two holes were open here. Turning encryption on only ever protected the *next*
write, so an operator who set the passphrase still had every existing key in
the clear and their backups still had to blank them — a setting that looked
done and was not. And nothing could consume a backup: they were produced,
hardened, described, and no code path ever restored one.

Restoring is the only operation in this codebase that destroys something on
purpose, so most of what follows is about it refusing, undoing, or keeping a
copy of what it replaced.
"""

import shutil
import zipfile
from pathlib import Path

import pytest

from corparius import backup
from corparius.store import Store

SECRET = "gsk-this-must-survive-a-round-trip"


def _read(path, name):
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def _contents(path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        return b"".join(zf.read(n) for n in zf.namelist())


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    return tmp_path


def _company(home, slug="acme", body="slug: acme"):
    folder = home / "companies" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "company.yaml").write_text(body, encoding="utf-8")
    return folder


# --- what the passphrase buys ----------------------------------------------


def test_turning_encryption_on_rewrites_what_is_already_stored(home, monkeypatch):
    """The gap that made the setting mean less than it said."""
    pytest.importorskip("cryptography")
    from corparius import cfg

    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", SECRET, secret=True)
    assert store.secret_rows() == [{"key": "GROQ_API_KEY", "encrypted": False, "empty": False}]

    monkeypatch.setenv("CORP_SECRET_KEY", "a phrase")
    cfg.invalidate()
    assert store.rewrite_secrets(to_encrypted=True) == ["GROQ_API_KEY"]
    assert store.secret_rows()[0]["encrypted"] is True
    assert store.get_setting("GROQ_API_KEY") == SECRET, "and it still reads back"
    store.close()


def test_encryption_is_reversible_so_turning_it_on_is_not_a_trap(home, monkeypatch):
    """A one-way door is a door nobody opens."""
    pytest.importorskip("cryptography")
    from corparius import cfg

    monkeypatch.setenv("CORP_SECRET_KEY", "a phrase")
    cfg.invalidate()
    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", SECRET, secret=True)
    assert store.secret_rows()[0]["encrypted"] is True
    assert store.rewrite_secrets(to_encrypted=False) == ["GROQ_API_KEY"]
    assert store.secret_rows()[0]["encrypted"] is False
    assert store.get_setting("GROQ_API_KEY") == SECRET
    store.close()


def test_an_empty_secret_is_left_alone(home, monkeypatch):
    """There is nothing to protect, and encrypting an empty string would only
    make a blank field unreadable."""
    pytest.importorskip("cryptography")
    from corparius import cfg

    monkeypatch.setenv("CORP_SECRET_KEY", "a phrase")
    cfg.invalidate()
    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", "", secret=True)
    assert store.rewrite_secrets(to_encrypted=True) == []
    store.close()


def test_with_encryption_on_a_backup_needs_nothing_typed_back_in(home, monkeypatch):
    """The whole argument for the setting: the backup restores in full, and is
    still useless to anyone without the passphrase."""
    pytest.importorskip("cryptography")
    from corparius import cfg

    monkeypatch.setenv("CORP_SECRET_KEY", "a phrase kept in a password manager")
    cfg.invalidate()
    _company(home)
    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", SECRET, secret=True)
    store.close()

    path = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))
    blob = _contents(path)
    assert SECRET.encode() not in blob
    assert b"a phrase kept in a password manager" not in blob
    assert "No secret had to be blanked" in _read(path, backup.NOTE).decode()


def test_the_key_survives_a_backup_and_a_restore(home, monkeypatch):
    """End to end, which is the only way this claim means anything."""
    pytest.importorskip("cryptography")
    from corparius import cfg

    monkeypatch.setenv("CORP_SECRET_KEY", "a phrase")
    cfg.invalidate()
    _company(home)
    store = Store(str(home / "data"))
    store.set_setting("GROQ_API_KEY", SECRET, secret=True)
    store.close()
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))

    shutil.rmtree(home / "data")
    shutil.rmtree(home / "companies" / "acme")

    done = backup.restore(archive, str(home / "data"))
    assert done["blanked"] == []
    store = Store(str(home / "data"))
    assert store.get_setting("GROQ_API_KEY") == SECRET
    store.close()


def test_the_passphrase_is_its_own_paragraph_not_a_line_to_re_enter(home, monkeypatch):
    """Every other blanked name means "type it back in". This one must not: it
    has to come from where the operator saved it, and a backup carrying it
    would be a locked box shipped with its key."""
    from corparius import paths

    env = home / ".env"
    env.write_text("CORP_SECRET_KEY=phrase\n", encoding="utf-8")
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    _company(home)
    path = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))
    note = _read(path, backup.NOTE).decode()
    assert "  CORP_SECRET_KEY" not in note, "not an item in the list"
    assert "removed on purpose" in note and "password manager" in note


# --- restoring -------------------------------------------------------------


def test_a_restore_puts_a_company_and_its_state_back(home):
    """Backups were being made and nothing could consume one."""
    _company(home)
    store = Store(str(home / "data"))
    store.save_state("acme", {"tick": 42})
    store.close()
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))

    shutil.rmtree(home / "companies" / "acme")
    shutil.rmtree(home / "data")

    done = backup.restore(archive, str(home / "data"))
    assert "companies/acme" in done["replaced"] and "the store" in done["replaced"]
    store = Store(str(home / "data"))
    assert store.load_state("acme") == {"tick": 42}
    store.close()


def test_a_restore_backs_up_what_it_is_about_to_replace(home):
    """Someone restoring is already having a bad day. This must not be the step
    that makes it worse."""
    _company(home, body="the version in the archive")
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))
    _company(home, body="the version on this machine")

    done = backup.restore(archive, str(home / "data"))
    assert Path(done["safety_backup"]).is_file()
    with zipfile.ZipFile(done["safety_backup"]) as zf:
        kept = [n for n in zf.namelist() if "acme" in n.replace("\\", "/")]
        assert zf.read(kept[0]) == b"the version on this machine"


def test_a_failed_restore_is_undone_rather_than_left_half_done(home, monkeypatch):
    """Found on the first real run of this: a recursive delete failed on
    Windows *after* an earlier company had already been replaced, leaving a
    half-restore with nothing to undo. Every step renames aside now."""
    for slug in ("aaa", "zzz"):
        _company(home, slug, "from-the-archive")
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))
    for slug in ("aaa", "zzz"):
        _company(home, slug, "on-this-machine")

    real_move = shutil.move
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("the disk said no")
        return real_move(src, dst)

    monkeypatch.setattr(backup.shutil, "move", flaky)
    with pytest.raises(backup.RestoreError, match="undone"):
        backup.restore(archive, str(home / "data"))
    for slug in ("aaa", "zzz"):
        got = (home / "companies" / slug / "company.yaml").read_text(encoding="utf-8")
        assert got == "on-this-machine", f"{slug} was left restored after a failure"


def test_an_archive_that_is_not_a_backup_is_refused_before_anything_moves(home):
    junk = home / "holiday-photos.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("beach.jpg", "not a company")
    with pytest.raises(backup.RestoreError, match="not a corparius backup"):
        backup.restore(junk, str(home / "data"))


def test_something_that_is_not_a_zip_is_refused(home):
    notzip = home / "notes.txt"
    notzip.write_text("hello", encoding="utf-8")
    with pytest.raises(backup.RestoreError, match="not a readable zip"):
        backup.restore(notzip, str(home / "data"))


def test_a_crafted_archive_cannot_write_outside_the_staging_area(home):
    """Zip-slip. An archive is a file someone was handed; it does not get to
    choose where its members land."""
    evil = home / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("companies/acme/company.yaml", "slug: acme")
        zf.writestr("../../escaped.txt", "should never be written")
    with pytest.raises(backup.RestoreError, match="unsafe path"):
        backup.restore(evil, str(home / "data"))
    assert not (home.parent / "escaped.txt").exists()


def test_a_restore_never_overwrites_the_passphrase_with_a_blank(home, monkeypatch):
    """The archive's CORP_SECRET_KEY line is deliberately empty. Copying it
    over would erase the one thing that opens the ciphertext being restored."""
    from corparius import paths

    env = home / ".env"
    env.write_text("CORP_SECRET_KEY=the phrase\nCORP_LLM_MOCK=false\n", encoding="utf-8")
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    _company(home)
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))

    backup.restore(archive, str(home / "data"))
    assert "CORP_SECRET_KEY=the phrase" in env.read_text(encoding="utf-8")


def test_inspect_reads_an_archive_without_unpacking_it_anywhere_real(home):
    _company(home)
    Store(str(home / "data")).close()
    archive = backup.make_backup(str(home / "data"), out_dir=str(home / "out"))
    found = backup.inspect(archive)
    assert found["companies"] == ["acme"] and found["has_store"] is True
    assert not (home / "companies" / "acme" / "unpacked").exists()

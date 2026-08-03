"""A backup that quietly omits the store, or that carries a deleted company
forward, is worse than no backup: the operator finds out at restore time.

The warning matters as much as the archive. This design created the fact that a
backup zip holds the console's API keys in the clear, so `describe()` is the one
place that has to keep saying so.
"""

import zipfile
from pathlib import Path

import pytest

from corparius import backup


def _tree(tmp_path):
    """A writable home shaped like a real install: data/ next to companies/."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "corparius.sqlite").write_text("db", encoding="utf-8")
    companies = tmp_path / "companies"
    (companies / "acme").mkdir(parents=True)
    (companies / "acme" / "company.yaml").write_text("slug: acme", encoding="utf-8")
    (companies / ".trash" / "gone").mkdir(parents=True)
    (companies / ".trash" / "gone" / "company.yaml").write_text("slug: gone", encoding="utf-8")
    return data


def _names(path):
    with zipfile.ZipFile(path) as zf:
        return {n.replace("\\", "/") for n in zf.namelist()}


def test_backup_carries_the_store_and_the_companies(tmp_path, monkeypatch):
    data = _tree(tmp_path)
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    names = _names(backup.make_backup(str(data), out_dir=str(tmp_path / "out")))
    assert "data/corparius.sqlite" in names
    assert "companies/acme/company.yaml" in names


def test_deleted_companies_are_not_carried_forward(tmp_path, monkeypatch):
    """companies/.trash is where a deleted company goes instead of being erased;
    restoring a backup must not resurrect it."""
    data = _tree(tmp_path)
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    names = _names(backup.make_backup(str(data), out_dir=str(tmp_path / "out")))
    assert not any(".trash" in n for n in names)


def test_a_data_dir_outside_the_home_is_still_archived(tmp_path, monkeypatch):
    """CORP_DATA_PATH can point anywhere, so relative_to(ROOT) raises and the
    walk falls back to the directory's own name. Without that branch the store
    would be dropped from the archive without a word."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path / "home"))
    # exist_ok: tmp_path/"home" is the private home the hermetic fixture already
    # made, which is what keeps every test off the checkout.
    (tmp_path / "home").mkdir(exist_ok=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "corparius.sqlite").write_text("db", encoding="utf-8")
    names = _names(backup.make_backup(str(outside), out_dir=str(tmp_path / "out")))
    assert "elsewhere/corparius.sqlite" in names


def test_missing_directories_are_skipped_not_fatal(tmp_path, monkeypatch):
    """First run backs up before any company exists."""
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    path = backup.make_backup(str(tmp_path / "absent"), out_dir=str(tmp_path / "out"))
    assert path.is_file()


def test_the_stamp_names_the_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    path = backup.make_backup(
        str(_tree(tmp_path)), out_dir=str(tmp_path / "out"), stamp="20260720-101500"
    )
    assert path.name == "corparius-backup-20260720-101500.zip"


def test_describe_warns_about_the_keys_in_both_languages(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    path = backup.make_backup(str(_tree(tmp_path)), out_dir=str(tmp_path / "out"))
    assert backup.WARNING_EN in backup.describe(path)
    assert backup.WARNING_FR in backup.describe(path, "fr")
    assert path.name in backup.describe(path)


# --- a backup you can keep somewhere ---------------------------------------
#
# The archive used to hold every API key in the clear, and said so. That made
# the only safe place for a backup nowhere: not a NAS, not a mail to yourself,
# not a private repo — repos go public by accident more often than laptops die.
# The rule now is flat, and these tests are it: no plaintext secret ever leaves
# in a backup unless someone asked for that in so many words.

SECRET = "sk-or-v1-this-must-never-leave-the-machine"


def _real_store(tmp_path, monkeypatch, **settings):
    from corparius.store import Store

    data = tmp_path / "data"
    store = Store(str(data))
    for key, value in settings.items():
        store.set_setting(key, value, secret=key in backup._secret_names())
    store.close()
    companies = tmp_path / "companies"
    (companies / "acme").mkdir(parents=True)
    (companies / "acme" / "company.yaml").write_text("slug: acme", encoding="utf-8")
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    return data


def _read(path, name):
    with zipfile.ZipFile(path) as zf:
        return zf.read(name)


def _contents(path) -> bytes:
    """Every member, decompressed and concatenated.

    Searching the .zip bytes directly proves nothing: DEFLATE can hide a string
    that is plainly there, which is exactly how a "the key does not leak" test
    passes while the key leaks.
    """
    with zipfile.ZipFile(path) as zf:
        return b"".join(zf.read(n) for n in zf.namelist())


def test_a_key_saved_from_the_console_never_leaves_in_a_backup(tmp_path, monkeypatch):
    """The store holds it in the clear unless CORP_SECRET_KEY is set, so the
    copy that goes in the zip is the one that gets blanked."""
    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    assert SECRET.encode() not in _contents(path), "the secret is somewhere in the archive"


def test_the_names_are_kept_so_a_restore_says_what_to_re_enter(tmp_path, monkeypatch):
    """Blanking without saying what was blanked turns a restore into a hunt."""
    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    note = _read(path, backup.NOTE).decode()
    assert "OPENROUTER_API_KEY" in note
    # And how to stop having to: the command, not the variable. Telling someone
    # to set CORP_SECRET_KEY used to leave their existing keys in the clear.
    assert "corparius secrets on" in note


def test_everything_that_is_not_a_secret_still_restores(tmp_path, monkeypatch):
    """Redaction has to be surgical: tiers, toggles and endpoints are the
    settings that make a restore worth doing."""
    import sqlite3

    data = _real_store(
        tmp_path,
        monkeypatch,
        OPENROUTER_API_KEY=SECRET,
        CORP_TRIVIAL_MODEL="openrouter:free-model",
        CORP_OLLAMA_URL="http://localhost:11434",
    )
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    restored = tmp_path / "restored.sqlite"
    restored.write_bytes(_read(path, "data/corparius.sqlite"))
    db = sqlite3.connect(restored)
    kept = dict(db.execute("SELECT key, value FROM settings").fetchall())
    db.close()
    assert kept["CORP_TRIVIAL_MODEL"] == "openrouter:free-model"
    assert kept["CORP_OLLAMA_URL"] == "http://localhost:11434"
    assert kept["OPENROUTER_API_KEY"] == ""


def test_an_encrypted_secret_rides_along_because_it_is_not_readable(tmp_path, monkeypatch):
    """This is what CORP_SECRET_KEY buys: a backup that restores in full. The
    archive is useless without the passphrase, which is not in it."""
    pytest.importorskip("cryptography")
    monkeypatch.setenv("CORP_SECRET_KEY", "a passphrase kept elsewhere")
    from corparius import cfg

    cfg.invalidate()
    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    blob = _contents(path)
    assert SECRET.encode() not in blob
    assert b"a passphrase kept elsewhere" not in blob
    assert "OPENROUTER_API_KEY" not in _read(path, backup.NOTE).decode(), "nothing was lost"


def test_the_settings_file_is_archived_with_its_secrets_blanked(tmp_path, monkeypatch):
    """.env was never in a backup, so a restore lost every bootstrap toggle.
    It is in now — with the shape kept and the values gone."""
    from corparius import paths

    env = tmp_path / ".env"
    env.write_text(
        "# my notes\nCORP_LLM_MOCK=false\nOPENROUTER_API_KEY=" + SECRET + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    data = _real_store(tmp_path, monkeypatch)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    got = _read(path, ".env").decode()
    assert "CORP_LLM_MOCK=false" in got, "the settings that are not secrets restore"
    assert "# my notes" in got, "and the file the operator hand-edited is not rewritten"
    assert "OPENROUTER_API_KEY=" in got and SECRET not in got
    assert SECRET.encode() not in _contents(path)


def test_asking_for_the_secrets_in_so_many_words_keeps_them(tmp_path, monkeypatch):
    """A disaster-recovery copy on an encrypted disk is a legitimate thing to
    want. It has to be asked for, and it says what it is."""
    from corparius import paths

    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=" + SECRET + "\n", encoding="utf-8")
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"), with_secrets=True)
    assert SECRET.encode() in _contents(path)
    said = backup.describe(Path(path), with_secrets=True)
    assert "PLAINTEXT" in said and "password" in said


def test_the_default_warning_no_longer_calls_the_archive_a_password(tmp_path, monkeypatch):
    """It said "treat this like a password" because it was one. It is not any
    more, and saying so is what makes people keep backups."""
    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    for lang in ("en", "fr"):
        said = backup.describe(Path(path), lang=lang)
        assert "no API key" in said or "aucune clé API" in said
        assert "keep it private" in said or "gardez-la" in said


def test_a_store_sqlite_cannot_read_is_carried_anyway(tmp_path, monkeypatch):
    """An archive quietly missing the store is the failure this module exists
    to prevent, and a file SQLite refuses to open holds no settings table."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "corparius.sqlite").write_bytes(b"not a database at all")
    monkeypatch.setenv("CORP_HOME", str(tmp_path))
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    assert _read(path, "data/corparius.sqlite") == b"not a database at all"


def test_the_live_store_is_never_modified(tmp_path, monkeypatch):
    """Redaction happens on the copy. Blanking the operator's own keys while
    backing them up would be the worst bug this file could have."""
    from corparius.store import Store

    data = _real_store(tmp_path, monkeypatch, OPENROUTER_API_KEY=SECRET)
    backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    store = Store(str(data))
    assert store.get_setting("OPENROUTER_API_KEY") == SECRET
    store.close()


def test_the_passphrase_never_travels_with_the_ciphertext_it_opens(tmp_path, monkeypatch):
    """The property the whole at-rest design rests on. CORP_SECRET_KEY lives in
    .env, and .env is now inside the archive — so if it were not redacted, a
    stolen backup would carry both the locked box and its key. It is the first
    thing to check after putting .env in there, not the last."""
    from corparius import paths

    env = tmp_path / ".env"
    env.write_text("CORP_SECRET_KEY=the passphrase\nCORP_LLM_MOCK=false\n", encoding="utf-8")
    monkeypatch.setattr(paths, "dotenv_file", lambda: env)
    data = _real_store(tmp_path, monkeypatch)
    path = backup.make_backup(str(data), out_dir=str(tmp_path / "out"))
    assert b"the passphrase" not in _contents(path)
    assert "CORP_SECRET_KEY" in _read(path, backup.NOTE).decode()


def test_a_backup_never_reaches_the_operators_real_home(tmp_path, monkeypatch):
    """The home was captured at import, before any fixture had redirected
    anything — so a console test archived the developer's own companies, 139
    files of them, and took 33 seconds doing it. Resolved per call now, which
    is the same lesson cli._store() learned: a module-level snapshot of a
    layered setting is a snapshot of the wrong layer."""
    from corparius import backup as mod

    assert not hasattr(mod, "ROOT"), "an import-time snapshot is what caused this"
    monkeypatch.setenv("CORP_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "companies" / "only-this-one").mkdir(parents=True)
    (tmp_path / "home" / "companies" / "only-this-one" / "company.yaml").write_text("x", "utf-8")
    data = tmp_path / "data"
    data.mkdir()
    names = _names(mod.make_backup(str(data), out_dir=str(tmp_path / "out")))
    assert any("only-this-one" in n for n in names)
    assert all("CorpariusHome" not in n for n in names)

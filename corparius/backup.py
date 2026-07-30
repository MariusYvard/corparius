"""Zip the store, the company configs and the settings file.

A backup nobody dares keep is not a backup. This one used to carry every API
key in the clear — the store holds the ones saved from the console, and the
module said so and asked the operator to treat the file like a password. That
made the safest place for a backup nowhere: not a NAS, not a mail to yourself,
not a private repo, because a repo goes public by accident more often than a
laptop dies.

So the rule here is now flat: **a backup never writes a secret in plaintext.**

  * A settings row already encrypted at rest (CORP_SECRET_KEY is set) rides
    along as ciphertext. It restores, and the archive is useless without the
    passphrase, which lives elsewhere.
  * Anything else that is a secret is blanked, and its *name* is listed in
    REDACTED.txt so a restore says exactly what to type back in.
  * `with_secrets=True` keeps them, because a disaster-recovery copy on an
    encrypted disk is a legitimate thing to want. It has to be asked for.

That turns CORP_SECRET_KEY from a chore into the thing that buys a complete
backup, which is a better argument for it than any warning was.

The store is snapshotted through SQLite's own backup API rather than copied as
a file: a live database plus a separate -wal is not a consistent pair, and the
whole point of this file is producing something that will actually restore.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from . import paths


# The writable home: backups land under it and it anchors the archive paths. In
# a source checkout this is the repository root (unchanged); frozen, it is the
# per-OS data directory, so the backup carries the operator's real store and
# companies rather than anything inside the read-only bundle.
#
# Resolved per call, never captured at import. Captured, it froze whatever
# CORP_HOME said the moment this module was first imported — which in the test
# suite is before any fixture has redirected anything, so a console test
# archived the developer's own 139 company files and took 33 seconds doing it.
# Same lesson as cli._store(): a module-level snapshot of a layered setting is
# a snapshot of the wrong layer.
def _home() -> Path:
    return paths.user_home()


BLANK = ""
NOTE = "REDACTED.txt"

WARNING_EN = (
    "This archive holds no API key in plaintext: secrets are either encrypted "
    "(CORP_SECRET_KEY) or blanked, and REDACTED.txt names what to re-enter. It "
    "still holds your companies and your journal, so keep it private."
)
WARNING_FR = (
    "Cette archive ne contient aucune clé API en clair : les secrets sont soit "
    "chiffrés (CORP_SECRET_KEY), soit vidés, et REDACTED.txt nomme ce qu'il "
    "faudra ressaisir. Elle contient vos entreprises et votre journal : gardez-la "
    "privée."
)
WARNING_SECRETS_EN = (
    "This archive contains API keys IN PLAINTEXT because it was asked for with "
    "--with-secrets. Treat the file exactly like a password: never a shared "
    "drive, never a repository, never an email."
)
WARNING_SECRETS_FR = (
    "Cette archive contient des clés API EN CLAIR parce qu'elle a été demandée "
    "avec --with-secrets. Traitez le fichier exactement comme un mot de passe : "
    "jamais un disque partagé, jamais un dépôt, jamais un e-mail."
)


def _secret_names() -> set[str]:
    from .settings_spec import SECRETS

    return set(SECRETS)


def _redact_env(text: str, redacted: list[str]) -> str:
    """Blank the value of every secret line, keep the rest verbatim.

    The keys stay, so a restored .env has the right shape and the operator sees
    which blanks to fill. Comments and unrelated lines are untouched — this is
    the file they hand-edited.
    """
    secrets = _secret_names()
    out = []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in secrets:
            if line.split("=", 1)[1].strip():
                redacted.append(key)
            out.append(f"{key}={BLANK}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _snapshot_store(source: Path, destination: Path, keep_secrets: bool, redacted: list[str]):
    """A consistent copy of the store, with its plaintext secrets removed.

    Redacting the copy rather than the original is the whole trick: the running
    store is untouched, and what leaves the machine is a database that never
    held the key.
    """
    import shutil

    from . import secretbox

    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error:
        # Not a database this build can open. Carry the bytes rather than drop
        # the store: an archive quietly missing it is the failure this whole
        # module exists to prevent, and a file SQLite refuses to read is not a
        # file holding a settings table.
        shutil.copyfile(source, destination)
        return
    try:
        dst = sqlite3.connect(destination)
        try:
            try:
                src.backup(dst)
            except sqlite3.DatabaseError:
                dst.close()
                destination.unlink(missing_ok=True)
                shutil.copyfile(source, destination)
                return
            if keep_secrets:
                return
            dst.row_factory = sqlite3.Row
            try:
                rows = dst.execute("SELECT key, value, secret FROM settings").fetchall()
            except sqlite3.DatabaseError:
                return  # no settings table yet: nothing to redact
            names = _secret_names()
            for row in rows:
                value = row["value"] or ""
                is_secret = bool(row["secret"]) or row["key"] in names
                if not is_secret or not value or secretbox.is_encrypted(value):
                    continue  # not a secret, empty, or already ciphertext
                dst.execute("UPDATE settings SET value=? WHERE key=?", (BLANK, row["key"]))
                redacted.append(row["key"])
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def _note(redacted: list[str], kept_encrypted: bool) -> str:
    if not redacted:
        return "No secret had to be blanked: this backup is complete.\n" + (
            "Encrypted values ride along as ciphertext.\n" if kept_encrypted else ""
        )
    names = "\n".join(f"  {n}" for n in sorted(set(redacted)))
    return (
        "These settings were blanked so this archive holds no key in plaintext.\n"
        "Re-enter them after a restore, from the console or in .env:\n\n"
        f"{names}\n\n"
        "To keep them in future backups, set CORP_SECRET_KEY: values are then\n"
        "encrypted at rest and travel as ciphertext, useless without the\n"
        "passphrase. See docs/securite.md.\n"
    )


def make_backup(
    data_path: str,
    out_dir: str | None = None,
    stamp: str | None = None,
    with_secrets: bool = False,
) -> Path:
    home = _home()
    out = Path(out_dir or home / "backups")
    out.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    path = out / f"corparius-backup-{stamp}.zip"
    redacted: list[str] = []
    store = Path(data_path) / "corparius.sqlite"

    with tempfile.TemporaryDirectory() as tmp:
        clean_store = Path(tmp) / "corparius.sqlite"
        if store.is_file():
            _snapshot_store(store, clean_store, with_secrets, redacted)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for base in (Path(data_path), home / "companies"):
                if not base.is_dir():
                    continue
                for root, _dirs, files in os.walk(base):
                    if ".trash" in Path(root).parts:
                        continue  # deleted companies are not worth carrying forward
                    for name in files:
                        full = Path(root) / name
                        # The snapshot below replaces these three: a live
                        # database and its -wal are not a consistent pair.
                        if full.name.startswith("corparius.sqlite"):
                            continue
                        try:
                            arc = full.relative_to(home)
                        except ValueError:
                            arc = Path(base.name) / full.relative_to(base)
                        zf.write(full, str(arc))
            if clean_store.is_file():
                zf.write(clean_store, str(Path(data_path).name + "/corparius.sqlite"))
            env = paths.dotenv_file()
            if env.is_file():
                raw = env.read_text(encoding="utf-8", errors="replace")
                zf.writestr(".env", raw if with_secrets else _redact_env(raw, redacted))
            zf.writestr(NOTE, _note(redacted, kept_encrypted=not redacted and not with_secrets))
    return path


def describe(path: Path, lang: str = "en", with_secrets: bool = False) -> str:
    size = path.stat().st_size / 1024
    if with_secrets:
        warn = WARNING_SECRETS_FR if lang == "fr" else WARNING_SECRETS_EN
    else:
        warn = WARNING_FR if lang == "fr" else WARNING_EN
    return f"{path.name} ({size:.0f} KB). {warn}"

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
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from .kernel import dotenv, paths


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


PASSPHRASE = "CORP_SECRET_KEY"


def _note(redacted: list[str], kept_encrypted: bool) -> str:
    names = sorted(set(redacted))
    # The passphrase is its own paragraph, never a line in the list. Everything
    # else here is "type it back in"; this one must come from wherever the
    # operator saved it, because a backup that carried it would be a backup
    # carrying the key to its own ciphertext.
    passphrase_note = ""
    if PASSPHRASE in names:
        names.remove(PASSPHRASE)
        passphrase_note = (
            f"\n{PASSPHRASE} was removed on purpose and is not recoverable from here.\n"
            "It is the phrase that opens the encrypted values in this archive, so a\n"
            "backup holding it would be a locked box shipped with its key. Take it\n"
            "from your password manager.\n"
        )
    if not names:
        return (
            "No secret had to be blanked: this backup is complete.\n"
            + ("Encrypted values ride along as ciphertext.\n" if kept_encrypted else "")
            + passphrase_note
        )
    listed = "\n".join(f"  {n}" for n in names)
    return (
        "These settings were blanked so this archive holds no key in plaintext.\n"
        "Re-enter them after a restore, from the console or in .env:\n\n"
        f"{listed}\n\n"
        "To keep them in future backups, run `corparius secrets on`: values are\n"
        "then encrypted at rest and travel as ciphertext, useless without the\n"
        "passphrase. See docs/securite.md.\n" + passphrase_note
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


class RestoreError(Exception):
    """A refusal an operator can act on, in one sentence."""


def _discard_path(path: Path) -> None:
    """Best effort, and never the reason a restore fails: what this removes is
    always a copy this function put there itself."""
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def inspect(archive: Path) -> dict:
    """What an archive holds, without unpacking it anywhere real.

    Restoring is the one operation here that destroys something, so it gets to
    be sure first: an archive that is not a corparius backup, or whose store
    will not open, must be refused while the operator still has theirs.
    """
    try:
        with zipfile.ZipFile(archive) as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
            note = zf.read(NOTE).decode("utf-8", "replace") if NOTE in names else ""
    except (OSError, zipfile.BadZipFile) as exc:
        raise RestoreError(f"{archive.name} is not a readable zip: {exc}") from exc
    stores = [n for n in names if n.endswith("/corparius.sqlite")]
    companies = sorted({n.split("/")[1] for n in names if n.startswith("companies/")})
    if not stores and not companies:
        raise RestoreError(
            f"{archive.name} holds neither a store nor a company; it is not a corparius backup"
        )
    blanked = [
        line.strip()
        for line in note.splitlines()
        if line.startswith("  ") and line.strip() and " " not in line.strip()
    ]
    return {
        "companies": companies,
        "has_store": bool(stores),
        "has_env": ".env" in names,
        "blanked": blanked,
        "note": note,
    }


def restore(archive: Path, data_path: str, keep_current: bool = True) -> dict:
    """Put an archive back, after backing up what it replaces.

    The order is the point: read and validate the archive, snapshot what is
    about to be overwritten, unpack to a staging directory, and only then move
    anything into place. An operator restoring is usually already having a bad
    day; this must not be the step that makes it worse.
    """
    archive = Path(archive)
    if not archive.is_file():
        raise RestoreError(f"no such file: {archive}")
    found = inspect(archive)

    home = _home()
    safety = ""
    if keep_current:
        try:
            safety = str(
                make_backup(data_path, stamp=time.strftime("%Y%m%d-%H%M%S-before-restore"))
            )
        except Exception as exc:  # noqa: BLE001
            raise RestoreError(
                f"could not back up what this would replace ({exc}); nothing was restored"
            ) from exc

    replaced: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "unpacked"
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                name = member.filename.replace("\\", "/")
                # Zip-slip: a crafted archive must not write outside staging.
                target = (staging / name).resolve()
                if not str(target).startswith(str(staging.resolve())):
                    raise RestoreError(f"{archive.name} contains an unsafe path: {name}")
                if member.is_dir():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))

        # Rename aside, never delete-then-move. A recursive delete fails on
        # Windows the moment anything holds a handle — it did, on the first
        # real run of this — and it fails *after* earlier companies have
        # already been replaced, leaving a half-restore with nothing to undo.
        # A rename is one atomic call, so every step is reversible until the
        # last one succeeds.
        aside: list[tuple[Path, Path]] = []
        stamp_suffix = f".replaced-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            for slug in found["companies"]:
                src = staging / "companies" / slug
                if not src.is_dir():
                    continue
                dst = home / "companies" / slug
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    kept = dst.parent / (slug + stamp_suffix)
                    _discard_path(kept)
                    os.replace(dst, kept)
                    aside.append((kept, dst))
                shutil.move(str(src), str(dst))
                replaced.append(f"companies/{slug}")

            data_dir = Path(data_path)
            for src in staging.rglob("corparius.sqlite"):
                data_dir.mkdir(parents=True, exist_ok=True)
                live = data_dir / "corparius.sqlite"
                if live.exists():
                    kept = data_dir / ("corparius.sqlite" + stamp_suffix)
                    _discard_path(kept)
                    os.replace(live, kept)
                    aside.append((kept, live))
                for stale in ("corparius.sqlite-wal", "corparius.sqlite-shm"):
                    (data_dir / stale).unlink(missing_ok=True)
                shutil.move(str(src), str(live))
                replaced.append("the store")
                break
        except Exception as exc:  # noqa: BLE001 - any failure must be undone
            for kept, original in reversed(aside):
                _discard_path(original)
                try:
                    os.replace(kept, original)
                except OSError:
                    pass
            raise RestoreError(
                f"restore failed and was undone ({exc}); nothing on this machine changed"
            ) from exc
        for kept, _original in aside:
            _discard_path(kept)

        env = staging / ".env"
        if env.is_file():
            # Merged, never overwritten: the .env on this machine holds the
            # passphrase that opens the restored ciphertext, and the archive's
            # copy of that line is deliberately blank.
            _merge_restored_env(env.read_text(encoding="utf-8", errors="replace"))
            replaced.append(".env (values that were not blank)")

    return {
        "ok": True,
        "replaced": replaced,
        "blanked": found["blanked"],
        "safety_backup": safety,
    }


def _merge_restored_env(text: str) -> None:
    """Apply the archive's non-empty lines over the current .env.

    Blank values are skipped rather than written: they are what redaction left
    behind, and copying them over would erase the very keys the operator still
    has on this machine.
    """
    values = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        # A key with anything but name characters in it is not a key. The
        # archive is a file someone handed over, and .env is where the console's
        # own host allow-list lives — a crafted member should not get to write
        # a setting the operator never typed. The writer refuses line breaks
        # too; this is the boundary, that is the backstop.
        name = key.strip()
        if not name.replace("_", "").isalnum():
            continue
        if value.strip():
            values[name] = value.strip()
    if values:
        dotenv.merge_into(paths.dotenv_file(), values)


def describe(path: Path, lang: str = "en", with_secrets: bool = False) -> str:
    size = path.stat().st_size / 1024
    if with_secrets:
        warn = WARNING_SECRETS_FR if lang == "fr" else WARNING_SECRETS_EN
    else:
        warn = WARNING_FR if lang == "fr" else WARNING_EN
    return f"{path.name} ({size:.0f} KB). {warn}"

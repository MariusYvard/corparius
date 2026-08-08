"""Keeping the installation healthy: diagnose, back up, restore, update. Rank 6.

The four commands that act on the install rather than on a company, which is why not one of
them takes `--company`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..config.settings import Settings


def cmd_update(args) -> None:
    """Replace this build with the newest release.

    Only from the downloadable binary; from source or Docker it says what to do
    instead. The download is checked against the published SHA256SUMS before
    anything moves, and a backup of the store and the companies is taken first
    even though an update cannot reach them.
    """
    from .. import selfupdate, update_check

    blocked = selfupdate.why_not()
    if blocked:
        sys.exit(f"cannot update here: {blocked}")
    info = update_check.check()
    if not info.get("enabled"):
        print("The version check is off. Set CORP_UPDATE_CHECK=true to let corparius ask")
        print("GitHub once whether a newer release exists.")
        raise SystemExit(1)
    if not info.get("reachable"):
        sys.exit("could not reach GitHub to ask what the latest release is")
    if not info.get("update_available"):
        print(f"already on the newest release ({info['current']})")
        return
    tag = f"v{info['latest']}"
    if not args.yes:
        print(f"{info['current']} -> {info['latest']}")
        print("This downloads the new build, checks it against the published checksum")
        print("and replaces this program. Your companies and settings live in a separate")
        print("folder and are not touched; a backup is taken first anyway.")
        if input("continue? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("nothing was changed")
    try:
        done = selfupdate.apply(tag)
    except selfupdate.UpdateError as exc:
        sys.exit(str(exc))
    print(f"installed {done['installed']} at {done['path']}")
    if done["backup"]:
        print(f"backup: {done['backup']}")
    print(f"the build you were running is kept at {done['previous']} until the new one starts")
    print("start corparius again to run it")


def cmd_doctor(args) -> None:
    from ..doctor import main as doctor_main

    sys.exit(doctor_main(quiet=args.quiet))


def cmd_backup(args) -> None:
    from .. import backup

    path = backup.make_backup(Settings().data_path, args.out, with_secrets=args.with_secrets)
    print(f"backup written: {path}")
    print(backup.describe(path, with_secrets=args.with_secrets))


def cmd_restore(args) -> None:
    """Put a backup back, after backing up what it replaces.

    The destructive one. It validates the archive before touching anything,
    snapshots what is about to be overwritten, and says what it could not
    restore — a redacted key is not an error, but discovering it at the next
    tick would be.
    """
    from .. import backup

    archive = Path(args.archive)
    try:
        found = backup.inspect(archive)
    except backup.RestoreError as exc:
        sys.exit(str(exc))
    print(f"{archive.name} holds:")
    print(f"  companies : {', '.join(found['companies']) or 'none'}")
    print(f"  store     : {'yes' if found['has_store'] else 'no'}")
    print(f"  .env      : {'yes' if found['has_env'] else 'no'}")
    if not args.yes:
        print()
        print("This replaces those companies and the store on this machine.")
        print("What it replaces is backed up first.")
        if input("continue? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("nothing was changed")
    try:
        done = backup.restore(archive, Settings().data_path)
    except backup.RestoreError as exc:
        sys.exit(str(exc))
    print("restored: " + ", ".join(done["replaced"]))
    if done["safety_backup"]:
        print(f"what it replaced: {done['safety_backup']}")
    if done["blanked"]:
        print()
        print("These were blanked in that archive and have to be entered again:")
        for name in done["blanked"]:
            print(f"  {name}")


def register(sub) -> None:
    sp = sub.add_parser("doctor", help="diagnose the installation")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(fn=cmd_doctor)

    sp = sub.add_parser("backup", help="zip the store, companies and settings")
    sp.add_argument(
        "--with-secrets",
        action="store_true",
        help="keep API keys in plaintext (a disaster-recovery copy; treat it like a password)",
    )
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_backup)

    sp = sub.add_parser("restore", help="put a backup back (replaces companies and the store)")
    sp.add_argument("archive", help="path to a corparius-backup-*.zip")
    sp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    sp.set_defaults(fn=cmd_restore)

    sp = sub.add_parser("update", help="replace this build with the newest release")
    sp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    sp.set_defaults(fn=cmd_update)

"""`corparius secrets ...` — turn at-rest encryption on, and off again.

Encryption was a setting nobody could safely reach. Writing `CORP_SECRET_KEY`
into .env only affected the *next* write, so an operator who thought they had
turned it on still had every existing key in the clear — and their backups
still had to blank them. This is the command that makes the setting mean what
it says: it writes the passphrase, then rewrites what is already stored.

`off` exists because a one-way door is a door nobody opens. Turning encryption
on has to be undoable, or the honest advice would be "don't".
"""

from __future__ import annotations

import secrets as _secrets
import sys
from typing import NoReturn

from . import cfg
from .kernel import dotenv, paths


def _fail(msg: str) -> NoReturn:
    sys.exit(f"error: {msg}")


def _store():
    from .cli import _store as cli_store

    return cli_store()


def _write_env(value: str) -> None:
    """Put CORP_SECRET_KEY in .env, where cfg reads its lowest layer.

    It cannot live in the store: the store is what it decrypts, and a key
    inside the box it opens is not a key.
    """
    dotenv.merge_into(paths.dotenv_file(), {"CORP_SECRET_KEY": value})


def cmd_status(args) -> None:
    from . import secretbox

    store = _store()
    rows = store.secret_rows()
    held = [r for r in rows if not r["empty"]]
    encrypted = [r for r in held if r["encrypted"]]
    print(f"encryption: {'on' if secretbox.enabled() else 'off'} (CORP_SECRET_KEY)")
    print(f"cryptography installed: {'yes' if secretbox.available() else 'no'}")
    print(f"secrets stored: {len(held)}  encrypted: {len(encrypted)}")
    for row in sorted(held, key=lambda r: r["key"]):
        print(f"  {'encrypted' if row['encrypted'] else 'PLAINTEXT':<10} {row['key']}")
    if held and len(encrypted) != len(held):
        print("\nBackups blank the plaintext ones rather than carry them, so a restore")
        print("needs those typed back in. `corparius secrets on` fixes that.")


def cmd_on(args) -> None:
    from . import secretbox

    if not secretbox.available():
        _fail(
            "the `cryptography` package is not installed. "
            "pip install -r requirements-secrets.txt (the downloadable build ships it)."
        )
    store = _store()
    passphrase = (args.passphrase or "").strip() or _secrets.token_urlsafe(32)
    generated = not (args.passphrase or "").strip()

    _write_env(passphrase)
    cfg.invalidate()
    changed = store.rewrite_secrets(to_encrypted=True)

    print(f"encryption on. {len(changed)} stored secret(s) re-encrypted.")
    if generated:
        print("\n  CORP_SECRET_KEY=" + passphrase + "\n")
        print("Written to your .env. Copy it into a password manager now.")
    print(
        "\nThis is the only copy that opens your encrypted secrets. Backups carry\n"
        "them as ciphertext from here on, so they restore in full — and are\n"
        "useless to anyone without this phrase. Lose it and those secrets are\n"
        "gone: nothing in corparius can recover them."
    )


def cmd_off(args) -> None:
    """Decrypt back to plaintext, so turning it on was never a trap."""
    from . import secretbox

    if not secretbox.enabled():
        print("encryption is already off")
        return
    store = _store()
    try:
        changed = store.rewrite_secrets(to_encrypted=False)
    except Exception as exc:  # noqa: BLE001 - a wrong passphrase is the likely one
        _fail(
            f"could not decrypt the stored secrets: {exc}. "
            "CORP_SECRET_KEY must be the phrase they were encrypted with."
        )
    _write_env("")
    cfg.invalidate()
    print(f"encryption off. {len(changed)} secret(s) written back in plaintext.")
    print("Backups will blank them again rather than carry them.")


def add_parser(sub) -> None:
    pp = sub.add_parser("secrets", help="encrypt the stored API keys at rest")
    psub = pp.add_subparsers(dest="secrets_cmd", required=True)

    psub.add_parser("status", help="what is stored, and what is encrypted").set_defaults(
        fn=cmd_status
    )

    sp = psub.add_parser("on", help="encrypt at rest, including what is already stored")
    sp.add_argument("--passphrase", default="", help="use this one instead of generating it")
    sp.set_defaults(fn=cmd_on)

    psub.add_parser("off", help="decrypt back to plaintext").set_defaults(fn=cmd_off)

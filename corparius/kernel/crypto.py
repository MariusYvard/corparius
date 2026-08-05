"""Encryption of a secret at rest, given a passphrase. Rank 0: pure.

This is the half of the old `secretbox` that has no opinions. It takes a passphrase as an
argument and never asks anyone for one — which is what removes the import cycle that used to
exist here: `cfg` imported `secretbox` to decrypt the settings it read, and `secretbox`
imported `cfg` inside a function to find the passphrase. The comment recording that
workaround sat two lines above the import.

The policy half — whether encryption is *on*, and what to tell an operator whose
configuration is incomplete — lives in `corparius/secrets.py` at rank 1, where knowing about
configuration is allowed. Callers keep the one-argument API they already had.

Design (unchanged, and load-bearing):
  * Encryption is transparent. `encrypt` returns its input unchanged when there is no
    passphrase, so a write path needs no branching beyond "is this a secret".
  * Encrypted values carry an `enc:v1:` prefix, and that prefix is the only signal used to
    decide whether to decrypt — so the schema never changed and a store can hold a mix of
    old plaintext and new ciphertext.
  * The Fernet key is derived from the passphrase with scrypt. The salt is a fixed
    application constant: the threat model is offline access to the store file or a backup,
    where the passphrase — kept in the environment or .env, never in the store it would have
    to decrypt — is the secret that matters.

`cryptography` is an optional dependency and is imported inside the functions that need it,
so importing this module costs nothing and its absence is reported rather than assumed.
"""

from __future__ import annotations

from typing import Any

PREFIX = "enc:v1:"
# Fixed application salt; see the module docstring for why this is acceptable.
_SALT = b"corparius.secretbox.v1"

INSTALL_HINT = (
    "CORP_SECRET_KEY is set but the 'cryptography' package is not "
    "installed. Run: pip install -r requirements-secrets.txt "
    "(or pip install cryptography), or unset CORP_SECRET_KEY."
)


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def available() -> bool:
    """Whether the optional library is installed. About the library, not the configuration."""
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False


def _fernet(passphrase: str) -> Any:
    # `Any` because `Fernet` comes from an optional dependency: a real annotation would need
    # a module-level import, which is exactly what this module must not have.
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    key = hashlib.scrypt(passphrase.encode("utf-8"), salt=_SALT, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str, passphrase: str) -> str:
    """Encrypt a secret. A no-op when there is no passphrase, so callers can pass every
    secret through unconditionally. Raises when a passphrase is set but `cryptography` is
    missing, so the misconfiguration surfaces instead of plaintext being stored quietly."""
    if not passphrase:
        return value
    if not available():
        raise RuntimeError(INSTALL_HINT)
    if is_encrypted(value):
        return value
    token = _fernet(passphrase).encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(value: str, passphrase: str) -> str:
    """Decrypt what `encrypt` produced. Values that are not encrypted pass through. Raises
    when a value is encrypted but unreadable — no passphrase, missing library, wrong key —
    because returning the ciphertext as if it were the secret is worse than failing."""
    if not is_encrypted(value):
        return value
    if not passphrase:
        raise RuntimeError("an encrypted secret was found but CORP_SECRET_KEY is not set.")
    if not available():
        raise RuntimeError(INSTALL_HINT)
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(passphrase).decrypt(value[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("could not decrypt a secret: wrong CORP_SECRET_KEY?") from exc


def decrypt_safe(value: str, passphrase: str) -> str:
    """Like `decrypt` but never raises: on failure it returns the value unchanged.

    Used on read paths that must not bring down a whole settings load because one value
    cannot be read. The condition is not swallowed — the doctor reports it.
    """
    try:
        return decrypt(value, passphrase)
    except Exception:
        return value

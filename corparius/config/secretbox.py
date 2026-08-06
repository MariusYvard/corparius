"""Opt-in encryption of secrets at rest: the policy half. Rank 1.

By default corparius stores API keys in the clear in the SQLite store, which the doctor
flags. Set CORP_SECRET_KEY (a passphrase) to encrypt the secret settings at rest instead. It
is off by default so the offline mock mode needs no extra dependency; turning it on requires
the `cryptography` package (see requirements-secrets.txt).

The cryptography itself lives in `kernel/crypto.py`, which takes a passphrase as an argument
and imports nothing of ours. This module is the half that has opinions: where the passphrase
comes from, whether the feature is on, and what to tell an operator who set a passphrase
without installing the library. That split is what removed an import cycle — the old single
module was imported *by* `cfg` and imported `cfg` back, from inside a function, to find the
passphrase.

CORP_SECRET_KEY is a bootstrap key (cfg.BOOTSTRAP): it resolves from the environment or
.env, never from the store it would have to decrypt. `cfg` therefore reads it without this
module's help and calls `kernel.crypto` directly.

The one-argument API below is unchanged, so every caller — backup, doctor, secretscli,
store, webui — passes secrets through exactly as before.
"""

from __future__ import annotations

from ..kernel import crypto
from ..kernel.crypto import PREFIX, available, is_encrypted
from . import cfg

_INSTALL_HINT = crypto.INSTALL_HINT

__all__ = [
    "PREFIX",
    "available",
    "decrypt",
    "decrypt_safe",
    "enabled",
    "encrypt",
    "is_encrypted",
]


def _passphrase() -> str:
    return cfg.get("CORP_SECRET_KEY", "").strip()


def enabled() -> bool:
    """True when a passphrase is configured (encryption is requested)."""
    return bool(_passphrase())


def encrypt(value: str) -> str:
    """Encrypt a secret value. A no-op (returns the input) when encryption is off, so
    callers can pass every secret through unconditionally. Raises if a passphrase is set but
    `cryptography` is missing, so the misconfiguration is surfaced rather than silently
    storing plaintext."""
    return crypto.encrypt(value, _passphrase())


def decrypt(value: str) -> str:
    """Decrypt a value produced by `encrypt`. Non-encrypted values pass through unchanged.
    Raises if the value is encrypted but cannot be read (no passphrase, or `cryptography`
    missing, or the key is wrong)."""
    return crypto.decrypt(value, _passphrase())


def decrypt_safe(value: str) -> str:
    """Like `decrypt` but never raises: on failure it returns the value unchanged. Used on
    read paths that must not crash the whole settings load because one value cannot be
    decrypted; the doctor reports the condition."""
    return crypto.decrypt_safe(value, _passphrase())

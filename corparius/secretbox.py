"""Opt-in encryption of secrets at rest.

By default corparius stores API keys in the clear in the SQLite store, which the
doctor flags. Set CORP_SECRET_KEY (a passphrase) to encrypt the secret settings
at rest instead. It is off by default so the offline mock mode needs no extra
dependency; turning it on requires the `cryptography` package (see
requirements-secrets.txt).

Design:
  * Encryption is transparent to callers. `encrypt` returns its input unchanged
    when the feature is off, so write paths need no branching beyond "is this a
    secret". `decrypt`/`decrypt_safe` return non-encrypted values unchanged, so
    read paths cope with a mix of old plaintext and new ciphertext.
  * Encrypted values carry a "enc:v1:" prefix; that prefix is the only signal
    used to decide whether to decrypt, so the schema does not change.
  * The Fernet key is derived from the passphrase with scrypt. The salt is a
    fixed application constant: the threat model is offline access to the store
    file or a backup, where the passphrase (kept in .env / the environment, not
    in the store) is the secret that matters.

CORP_SECRET_KEY is a bootstrap key (corparius/cfg.BOOTSTRAP): it resolves from the
environment or .env, never from the store it would need to decrypt.
"""

from __future__ import annotations

PREFIX = "enc:v1:"
# Fixed application salt; see the module docstring for why this is acceptable.
_SALT = b"corparius.secretbox.v1"

_INSTALL_HINT = (
    "CORP_SECRET_KEY is set but the 'cryptography' package is not "
    "installed. Run: pip install -r requirements-secrets.txt "
    "(or pip install cryptography), or unset CORP_SECRET_KEY."
)


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _passphrase() -> str:
    # Lazy import: corparius/cfg imports this module, so importing it at module level
    # would be circular. By call time cfg is loaded.
    from . import cfg

    return cfg.get("CORP_SECRET_KEY", "").strip()


def available() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except ImportError:
        return False


def enabled() -> bool:
    """True when a passphrase is configured (encryption is requested)."""
    return bool(_passphrase())


def _fernet(passphrase: str):
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    key = hashlib.scrypt(passphrase.encode("utf-8"), salt=_SALT, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    """Encrypt a secret value. A no-op (returns the input) when encryption is
    off, so callers can pass every secret through unconditionally. Raises if a
    passphrase is set but `cryptography` is missing, so the misconfiguration is
    surfaced rather than silently storing plaintext."""
    passphrase = _passphrase()
    if not passphrase:
        return value
    if not available():
        raise RuntimeError(_INSTALL_HINT)
    if is_encrypted(value):
        return value
    token = _fernet(passphrase).encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt a value produced by `encrypt`. Non-encrypted values pass through
    unchanged. Raises if the value is encrypted but cannot be read (no
    passphrase, or `cryptography` missing, or the key is wrong)."""
    if not is_encrypted(value):
        return value
    passphrase = _passphrase()
    if not passphrase:
        raise RuntimeError("an encrypted secret was found but CORP_SECRET_KEY is not set.")
    if not available():
        raise RuntimeError(_INSTALL_HINT)
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(passphrase).decrypt(value[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("could not decrypt a secret: wrong CORP_SECRET_KEY?") from exc


def decrypt_safe(value: str) -> str:
    """Like `decrypt` but never raises: on failure it returns the value
    unchanged. Used on read paths that must not crash the whole settings load
    because one value cannot be decrypted; the doctor reports the condition."""
    try:
        return decrypt(value)
    except Exception:
        return value

"""Opt-in secrets-at-rest encryption. The default (no CORP_SECRET_KEY) must be
byte-identical to plaintext; with a key set, secret settings round-trip through
the store and the resolver transparently."""
import pytest

from app import cfg, secretbox
from app.store import Store

crypto = pytest.importorskip("cryptography")


def test_disabled_is_passthrough(monkeypatch):
    monkeypatch.delenv("CORP_SECRET_KEY", raising=False)
    cfg.invalidate()
    assert secretbox.enabled() is False
    assert secretbox.encrypt("sk-123") == "sk-123"        # no-op when off
    assert secretbox.decrypt("sk-123") == "sk-123"


def test_roundtrip_when_enabled(monkeypatch):
    monkeypatch.setenv("CORP_SECRET_KEY", "correct horse battery staple")
    cfg.invalidate()
    token = secretbox.encrypt("sk-secret-value")
    assert token.startswith(secretbox.PREFIX)
    assert "sk-secret-value" not in token                 # actually hidden
    assert secretbox.decrypt(token) == "sk-secret-value"
    assert secretbox.is_encrypted(token)


def test_decrypt_safe_never_raises_on_wrong_key(monkeypatch):
    monkeypatch.setenv("CORP_SECRET_KEY", "key-A")
    cfg.invalidate()
    token = secretbox.encrypt("value")
    monkeypatch.setenv("CORP_SECRET_KEY", "key-B")         # wrong key now
    cfg.invalidate()
    assert secretbox.decrypt_safe(token) == token          # returns as-is, no crash


def test_store_encrypts_secret_values_at_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_SECRET_KEY", "a strong passphrase")
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    store.set_setting("ANTHROPIC_API_KEY", "sk-live-xyz", secret=True)
    store.set_setting("CORP_UI_HOST", "127.0.0.1", secret=False)

    # Raw column: the secret is ciphertext, the non-secret is plaintext.
    raw = {r["key"]: r["value"] for r in
           store.db.execute("SELECT key, value FROM settings").fetchall()}
    assert raw["ANTHROPIC_API_KEY"].startswith(secretbox.PREFIX)
    assert "sk-live-xyz" not in raw["ANTHROPIC_API_KEY"]
    assert raw["CORP_UI_HOST"] == "127.0.0.1"

    # Reading through the store and the resolver returns plaintext.
    assert store.get_setting("ANTHROPIC_API_KEY") == "sk-live-xyz"
    assert cfg.get("ANTHROPIC_API_KEY") == "sk-live-xyz"


def test_store_plaintext_when_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CORP_SECRET_KEY", raising=False)
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path / "data"))
    cfg.invalidate()
    store = Store(str(tmp_path / "data"))
    store.set_setting("ANTHROPIC_API_KEY", "sk-plain", secret=True)
    raw = store.db.execute(
        "SELECT value FROM settings WHERE key='ANTHROPIC_API_KEY'").fetchone()[0]
    assert raw == "sk-plain"                                # unchanged default

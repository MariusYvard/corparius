"""The settings table the console writes and `config/store_layer` reads back."""

from __future__ import annotations

import time

from .base import Connected, _locked


class SettingsMixin(Connected):
    # Settings saved from the console. Global, not per company: they are the
    # second layer of corparius/cfg.py, under the real process environment.
    @_locked
    def all_settings(self) -> dict[str, str]:
        from ..config import secretbox

        rows = self.db.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: secretbox.decrypt_safe(r["value"]) for r in rows}

    @_locked
    def get_setting(self, key) -> str | None:
        from ..config import secretbox

        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return secretbox.decrypt_safe(row["value"]) if row else None

    @_locked
    def set_setting(self, key, value, secret: bool = False) -> None:
        # Secret values are encrypted at rest when CORP_SECRET_KEY is set;
        # encrypt() is a no-op otherwise, so plaintext stays the default.
        if secret:
            from ..config import secretbox

            value = secretbox.encrypt(value)
        self.db.execute(
            "INSERT OR REPLACE INTO settings (key, value, secret, updated_at) VALUES (?,?,?,?)",
            (key, value, 1 if secret else 0, time.time()),
        )
        self.db.commit()

    @_locked
    def delete_setting(self, key) -> bool:
        cur = self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def secret_rows(self) -> list[dict]:
        """Every stored secret, with whether it is currently ciphertext.

        The count is the honest answer to "is encryption actually on here?" —
        turning it on only affects the next write, so a store can have the
        passphrase set and still hold plaintext keys.
        """
        from ..config import secretbox

        rows = self.db.execute("SELECT key, value, secret FROM settings").fetchall()
        from ..config.settings_spec import SECRETS

        out = []
        for row in rows:
            if not (row["secret"] or row["key"] in SECRETS):
                continue
            out.append(
                {
                    "key": row["key"],
                    "encrypted": secretbox.is_encrypted(row["value"] or ""),
                    "empty": not (row["value"] or ""),
                }
            )
        return out

    @_locked
    def rewrite_secrets(self, to_encrypted: bool) -> list[str]:
        """Bring every stored secret to ciphertext, or back to plaintext.

        Without this, `CORP_SECRET_KEY` only ever protected the *next* write:
        an operator who turned encryption on still had every existing key in
        the clear, and a backup still had to blank them. Which made the setting
        look like it did something it did not do yet.

        Returns the names it changed. Empty values are skipped — there is
        nothing to protect, and encrypting "" would only make it unreadable.
        """
        from ..config import secretbox

        changed: list[str] = []
        for row in self.secret_rows.__wrapped__(self):  # already holding the lock
            if row["empty"]:
                continue
            if row["encrypted"] == to_encrypted:
                continue
            stored = self.db.execute(
                "SELECT value FROM settings WHERE key=?", (row["key"],)
            ).fetchone()["value"]
            plain = secretbox.decrypt(stored) if secretbox.is_encrypted(stored) else stored
            value = secretbox.encrypt(plain) if to_encrypted else plain
            self.db.execute(
                "UPDATE settings SET value=?, secret=1, updated_at=? WHERE key=?",
                (value, time.time(), row["key"]),
            )
            changed.append(row["key"])
        self.db.commit()
        return changed

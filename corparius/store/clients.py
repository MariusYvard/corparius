"""Devices allowed to reach this installation. Schema 20.

`CORP_UI_TOKEN` is one shared secret with no name, no scope and no way to withdraw it from one
device without changing it for all of them. That is fine for a console an operator opens on the
same machine, and it is the wrong shape the moment a second client exists: revoking a lost phone
should not log out the laptop.

Three things a row carries that a shared token cannot:

  * **a name**, so an operator revoking one knows what they are revoking;
  * **a scope** — `read` or `act`, and only those two. The plan is explicit that ten scopes is a
    permission system nobody will get right, and this product already has one of those in
    `config/permissions.py` for what an *agent* may do. What a *device* may do is a different and
    much smaller question: look, or also act;
  * **`revoked`**, which is a column and not a `DELETE`. A revoked device that comes back has to
    be told no by name, and a row that was deleted cannot say which device this was.

The secret is never stored. `token_hash` is SHA-256 over a per-client salt, and the reasoning for
SHA-256 rather than scrypt is measured in `kernel/tokens.py` and recorded in ADR 0009.

No `company` column, deliberately: a device is paired to an *installation*. Giving it one would
imply per-company devices, which nothing offers and which `purge_company` would then delete —
silently revoking a phone because a company was removed.
"""

from __future__ import annotations

import time

from ..kernel import tokens
from .base import Connected, _locked

READ = "read"
ACT = "act"
SCOPES = (READ, ACT)


class ClientsMixin(Connected):
    @_locked
    def pair_client(self, name: str, scope: str = READ) -> dict:
        """Mint a credential for a device and keep only what verifies it.

        Returns the presented string **once**. There is no way to ask for it again, and that is
        the point rather than an inconvenience: a store that could show it back is a store whose
        theft is enough to impersonate every paired device.
        """
        assert scope in SCOPES, f"{scope!r} is not a scope; there are two"
        client_id, secret, presented = tokens.mint()
        salt = tokens.new_salt()
        self.db.execute(
            "INSERT INTO clients (id, name, token_hash, salt, scopes, created_at, revoked)"
            " VALUES (?,?,?,?,?,?,0)",
            (
                client_id,
                name.strip() or "unnamed device",
                tokens.hash_secret(secret, salt),
                salt,
                scope,
                time.time(),
            ),
        )
        self.db.commit()
        return {"id": client_id, "name": name, "scope": scope, "token": presented}

    @_locked
    def client(self, client_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        return dict(row) if row else None

    @_locked
    def list_clients(self, include_revoked: bool = True) -> list[dict]:
        """Never the hash or the salt: an operator listing their devices has no use for either,
        and a payload that carries them is a payload that can leak them."""
        sql = "SELECT id, name, scopes, created_at, last_seen, revoked FROM clients"
        if not include_revoked:
            sql += " WHERE revoked=0"
        rows = self.db.execute(sql + " ORDER BY created_at DESC").fetchall()
        return [dict(r) | {"revoked": bool(r["revoked"])} for r in rows]

    @_locked
    def revoke_client(self, client_id: str) -> bool:
        cur = self.db.execute("UPDATE clients SET revoked=1 WHERE id=? AND revoked=0", (client_id,))
        self.db.commit()
        return cur.rowcount > 0

    @_locked
    def touch_client(self, client_id: str) -> None:
        """When this device was last heard from. Best effort and unconditional: an operator
        deciding whether a paired device is still in use needs this, and it is the only reason a
        successful authentication writes anything at all."""
        self.db.execute("UPDATE clients SET last_seen=? WHERE id=?", (time.time(), client_id))
        self.db.commit()

    @_locked
    def any_client(self) -> bool:
        """Whether this installation has ever paired a device that is still allowed.

        Read by the doctor: a paired device means somebody intends to reach this console from
        elsewhere, which changes what "bound off-loopback" means from a warning into a failure.
        """
        row = self.db.execute("SELECT 1 FROM clients WHERE revoked=0 LIMIT 1").fetchone()
        return row is not None

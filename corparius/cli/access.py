"""Which devices may reach this installation. Rank 6.

`CORP_UI_TOKEN` is one shared secret with no name and no way to withdraw it from one device
without changing it for all of them. These three commands are the other shape: pair a device, see
what is paired, revoke one.

From a terminal rather than the console, and that is deliberate: pairing is the bootstrap step, so
requiring the console for it would mean needing a paired device to pair a device. An operator over
SSH is exactly the person who needs this.
"""

from __future__ import annotations

from ..app.support import open_store
from ..store import clients as clients_store


def cmd_pair(args) -> int:
    """Mint a credential for one device and print it **once**.

    Printed once because it is stored as a hash: there is no way to ask for it again, which is the
    property rather than the inconvenience — a store whose theft is enough to impersonate every
    paired device is a store that should not hold these.
    """
    scope = clients_store.ACT if args.act else clients_store.READ
    store = open_store()
    try:
        paired = store.pair_client(args.name, scope)
    finally:
        store.close()
    print(f"paired {paired['name']!r} with scope {paired['scope']}")
    print()
    print(paired["token"])
    print()
    print("This is the only time it is shown. Put it in the device now.")
    print("The device sends it as:  Authorization: Bearer <token>")
    if scope == clients_store.READ:
        print("Scope 'read' can look and cannot act. Use --act for a device that starts runs.")
    return 0


def cmd_clients(args) -> int:
    """What is paired, including what has been revoked.

    Revoked rows are shown rather than hidden: an operator asking this question is often asking
    "did I actually revoke that phone", and an answer that omits it cannot say yes.
    """
    store = open_store()
    try:
        rows = store.list_clients()
    finally:
        store.close()
    if not rows:
        print("no paired device; the console answers to CORP_UI_TOKEN only")
        return 0
    for row in rows:
        seen = _ago(row["last_seen"])
        mark = "revoked" if row["revoked"] else row["scopes"]
        print(f"{row['id']}  {mark:8} {row['name'][:30]:32} last seen {seen}")
    return 0


def cmd_revoke(args) -> int:
    """Withdraw one device. Non-zero when nothing was withdrawn, because a script that revokes a
    lost phone needs to know the difference between "done" and "that id is not here"."""
    store = open_store()
    try:
        done = store.revoke_client(args.id)
    finally:
        store.close()
    if not done:
        print(f"no active device with id {args.id}")
        return 1
    print(f"revoked {args.id}; that device is refused from its next request")
    return 0


def _ago(ts) -> str:
    """ "never" rather than a date that is not there. A device paired and never used is the case an
    operator most wants to notice."""
    if not ts:
        return "never"
    import time

    seconds = max(0, int(time.time() - ts))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def register(sub) -> None:
    sp = sub.add_parser("pair", help="give a device its own credential (a phone, a second laptop)")
    sp.add_argument("--name", required=True, help="what this device is, so you can revoke it later")
    sp.add_argument("--act", action="store_true", help="let it start and stop runs, not only look")
    sp.set_defaults(fn=cmd_pair)

    sub.add_parser(
        "clients", help="what is paired, and when each was last heard from"
    ).set_defaults(fn=cmd_clients)

    sp = sub.add_parser("revoke", help="withdraw one device's credential")
    sp.add_argument("--id", required=True, help="from `corparius clients`")
    sp.set_defaults(fn=cmd_revoke)

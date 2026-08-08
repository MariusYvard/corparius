"""Writing settings, and the two per-company stores an operator edits by hand. Rank 6.

`set` is the console's own save path from a terminal: the same `app_settings.persist`, so the
same validation and the same choice of where a value lands — the store, or `.env` for the
bootstrap keys that must be readable before the store opens.

`memory` and `rules` are here because they are the same shape of act: a small, deliberate
correction to state the agents will read next tick.
"""

from __future__ import annotations

from ..app.support import open_store
from . import support


def cmd_set(args) -> None:
    """Write a setting from a terminal.

    The console could do this and the command line could not, which on a headless box meant
    editing .env by hand and guessing which of the two layers a key belongs to. The service
    behind it is `app.settings`, the same one the console's settings page calls — so the two
    refuse the same values for the same reasons, and neither can drift from the registry
    without the other noticing.
    """
    from ..app import settings as app_settings
    from ..config import cfg as cfg_mod
    from ..kernel import dotenv, paths

    values: dict[str, str] = {}
    for pair in args.pairs:
        if "=" not in pair:
            print(f"expected KEY=value, got {pair!r}")
            return
        key, _, value = pair.partition("=")
        values[key.strip()] = value
    unset = [k.strip() for k in (args.unset or "").split(",") if k.strip()]
    clean, drop, errors = app_settings.validate(values, unset)
    if errors:
        for err in errors:
            print(err)
        return
    if not clean and not drop:
        print("nothing to write")
        return
    store = open_store()
    try:
        meta = app_settings.persist(store, paths.dotenv_file(), clean, drop)
    except dotenv.LineBreakRefused as exc:
        # The service raises the failure, not a status code. A terminal shows it; the console
        # turns the same exception into a 400.
        print(exc)
        return
    for key, value in sorted(clean.items()):
        where = ".env (restart to take effect)" if key in cfg_mod.BOOTSTRAP else "the store"
        print(f"{key} = {value}   -> {where}")
    for key in sorted(drop):
        print(f"{key} cleared")
    if meta.get("shadowed"):
        print(
            "these are set in this process's environment, which outranks what was just "
            f"written: {', '.join(meta['shadowed'])}"
        )
    if meta.get("secrets_error"):
        print(meta["secrets_error"])
    elif meta.get("secrets_rewritten"):
        print(f"re-encrypted stored secrets: {', '.join(meta['secrets_rewritten'])}")


def cmd_memory(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
    if args.forget:
        print("forgotten" if store.forget(args.forget) else "no such memory")
        return
    if args.pin:
        print("pinned" if store.pin_memory(args.pin, True) else "no such memory")
        return
    rows = store.list_memory(cfg["slug"])
    print(f"== memory: {cfg.get('name')} ==")
    for r in rows:
        mark = "*" if r["pinned"] else " "
        why = f"  ({r['why']})" if r["why"] else ""
        print(f"{mark}#{r['id']:<4} [{r['agent']}] {r['fact']}{why}")
    if not rows:
        print("nothing learned yet; the CEO and strategy agents write here as they run")


def cmd_rules(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
    if args.revoke:
        print(
            f"revoked {args.revoke}"
            if store.drop_rule(cfg["slug"], args.revoke)
            else "no standing rule for that tool"
        )
        return
    rules = store.list_rules(cfg["slug"])
    print(f"== standing rules: {cfg.get('name')} ==")
    for r in rules:
        print(f"{r['tool']:32} {r['scope']}")
    if not rules:
        print("none; every gated tool still asks")


def register(sub) -> None:
    sp = sub.add_parser("set", help="write a setting (KEY=value ...), the console's own path")
    sp.add_argument("pairs", nargs="+", metavar="KEY=value")
    sp.add_argument("--unset", default="", help="comma-separated keys to clear")
    sp.set_defaults(fn=cmd_set)

    sp = support.with_company(sub.add_parser("memory"))
    sp.add_argument("--pin", type=int, default=0, help="memory id to pin")
    sp.add_argument("--forget", type=int, default=0, help="memory id to delete")
    sp.set_defaults(fn=cmd_memory)

    sp = support.with_company(sub.add_parser("rules"))
    sp.add_argument("--revoke", default="", help="tool name whose standing rule to drop")
    sp.set_defaults(fn=cmd_rules)

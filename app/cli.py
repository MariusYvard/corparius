"""Command line: init / run / status / approvals / approve / reject."""
from __future__ import annotations
import argparse
import json
import os
import sys

import yaml

from .config import settings, setup_logging
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _company_path(slug_or_path: str) -> str:
    if os.path.isfile(slug_or_path):
        return slug_or_path
    return os.path.join(ROOT, "companies", slug_or_path, "company.yaml")


def _load_company(slug_or_path: str) -> dict:
    path = _company_path(slug_or_path)
    if not os.path.isfile(path):
        sys.exit(f"company config not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg.setdefault("slug", os.path.basename(os.path.dirname(path)))
    return cfg


def cmd_init(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    store.save_state(cfg["slug"], {"tick": 0})
    on = [k for k, v in cfg.get("agents", {}).items() if v]
    print(f"initialised {cfg.get('name')} ({cfg['slug']}). agents on: {on}")


def cmd_run(args) -> None:
    from .orchestrator import Runtime
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    result = Runtime(settings, store).run(cfg, ticks=args.ticks, loop=args.loop)
    print(json.dumps(result, indent=2))


def cmd_status(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    s = store.status(cfg["slug"])
    tick = store.load_state(cfg["slug"]).get("tick", 0)
    print(f"== {cfg.get('name')} ({cfg['slug']}) ==")
    print(f"clock: tick {tick}")
    print(f"actions: {s['actions']}  tokens: {s['tokens']}  "
          f"pending approvals: {s['pending_approvals']}")
    for agent, n in sorted(s["by_agent"].items()):
        print(f"  {agent:12} {n}")


def cmd_approvals(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    rows = store.list_approvals(cfg["slug"], "pending")
    if not rows:
        print("no pending approvals")
        return
    for r in rows:
        print(f"{r['id']}  {r['agent']:10} {r['tool']:26} {r['parameters']}")


def cmd_decide(args, status: str) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    ok = store.set_approval_status(args.id, status, args.note or "")
    print(f"{args.id} -> {status}" if ok else "approval id not found")


def main(argv=None) -> None:
    setup_logging()
    p = argparse.ArgumentParser(prog="corparius",
                                description="Run autonomous AI micro-companies.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_company(sp):
        sp.add_argument("--company", required=True, help="slug or path to company.yaml")
        return sp

    with_company(sub.add_parser("init")).set_defaults(fn=cmd_init)

    sp = with_company(sub.add_parser("run"))
    sp.add_argument("--ticks", type=int, default=6, help="simulated hours to run")
    sp.add_argument("--loop", action="store_true", help="keep running day after day")
    sp.set_defaults(fn=cmd_run)

    with_company(sub.add_parser("status")).set_defaults(fn=cmd_status)
    with_company(sub.add_parser("approvals")).set_defaults(fn=cmd_approvals)

    sp = with_company(sub.add_parser("approve"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.set_defaults(fn=lambda a: cmd_decide(a, "approved"))

    sp = with_company(sub.add_parser("reject"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.set_defaults(fn=lambda a: cmd_decide(a, "rejected"))

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

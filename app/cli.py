"""Command line: init / run / status / approvals / approve / reject."""
from __future__ import annotations
import argparse
import json
import os
import sys

from . import company, paths
from .config import settings, setup_logging
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _company_path(slug_or_path: str) -> str:
    if os.path.isfile(slug_or_path):
        return slug_or_path
    # Route through the single company resolver so the CLI, console and MCP
    # server agree on where companies live (writable home, per-OS when frozen).
    return str(company.path_for(slug_or_path))


def _load_company(slug_or_path: str) -> dict:
    """Thin wrapper over company.load, keeping the CLI's exit-with-a-message
    ergonomics. The parsing, defaults and validation live in app/company.py so
    the CLI, the console and the MCP server cannot drift apart."""
    path = _company_path(slug_or_path)
    try:
        return company.load(path)
    except FileNotFoundError:
        sys.exit(f"company config not found: {path}")
    except ValueError as exc:
        sys.exit(str(exc))


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


def cmd_site(args) -> None:
    from . import sitegen
    cfg = _load_company(args.company)
    out_dir = str(paths.site_dir(settings.data_path, cfg["slug"]))
    path = sitegen.build_site(cfg, out_dir, headline=args.headline or None)
    print(f"sales site built: {path}")


def cmd_tasks(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    rows = store.list_tasks(cfg["slug"])
    if not rows:
        print("no tasks")
        return
    for t in rows:
        tool = t.get("tool") or "-"
        print(f"#{t['id']:<3} [{t['status']:<11}] p{t['priority']} {t['target']:<9} "
              f"{t['title']} [{tool}] (by {t['created_by']})")


def cmd_task(args) -> None:
    store = Store(settings.data_path)
    fields = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.priority is not None:
        fields["priority"] = args.priority
    if args.target is not None:
        fields["target"] = args.target
    if args.tool is not None:
        fields["tool"] = args.tool
    if fields:
        store.update_task(args.id, **fields)
    if args.approve:
        store.set_task_status(args.id, "approved", "validated via CLI")
    elif args.reject:
        store.set_task_status(args.id, "rejected", "refused via CLI")
    print(f"task {args.id} updated")


def cmd_deploy(args) -> None:
    from . import sitegen, deploy
    cfg = _load_company(args.company)
    out_dir = str(paths.site_dir(settings.data_path, cfg["slug"]))
    if not os.path.exists(os.path.join(out_dir, "index.html")):
        sitegen.build_site(cfg, out_dir)
    print("deployed: " + deploy.deploy_site(out_dir))


def cmd_flow(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    fm = store.flow_metrics(cfg["slug"])
    print(f"== flow: {cfg.get('name')} ==")
    print(f"throughput(done): {fm['throughput']}   wip: {fm['wip']}   "
          f"tokens/task: {fm['tokens_per_completed_task']}   "
          f"bottleneck: {fm['bottleneck'] or 'none'}")
    print(f"waste: {fm['defects']} defects (failed actions), "
          f"{fm['waiting']} waiting (pending approvals)")
    for t, n in sorted(fm["by_target"].items()):
        print(f"  {t:12} {n} open")


def cmd_board(args) -> None:
    cfg = _load_company(args.company)
    store = Store(settings.data_path)
    rows = store.list_tasks(cfg["slug"])
    print(f"== board: {cfg.get('name')} ==")
    for col in ("proposed", "approved", "in_progress", "done", "rejected"):
        items = [t for t in rows if t["status"] == col]
        head = ", ".join(f"#{t['id']}:{t['target']}" for t in items[:6])
        print(f"{col:12} ({len(items)}): {head}")


def cmd_doctor(args) -> None:
    from .doctor import main as doctor_main
    sys.exit(doctor_main(quiet=args.quiet))


def cmd_backup(args) -> None:
    from . import backup
    path = backup.make_backup(settings.data_path, args.out)
    print(f"backup written: {path}")
    print(backup.WARNING_EN)


def cmd_ui(args) -> None:
    from .webui import serve
    raise SystemExit(serve(settings, host=args.host, port=args.port))


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

    sp = with_company(sub.add_parser("site"))
    sp.add_argument("--headline", default="", help="override the hero headline")
    sp.set_defaults(fn=cmd_site)

    with_company(sub.add_parser("deploy")).set_defaults(fn=cmd_deploy)
    with_company(sub.add_parser("tasks")).set_defaults(fn=cmd_tasks)

    sp = with_company(sub.add_parser("task"))
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--title")
    sp.add_argument("--target")
    sp.add_argument("--tool")
    sp.add_argument("--priority", type=int)
    sp.add_argument("--approve", action="store_true")
    sp.add_argument("--reject", action="store_true")
    sp.set_defaults(fn=cmd_task)

    with_company(sub.add_parser("flow")).set_defaults(fn=cmd_flow)
    with_company(sub.add_parser("board")).set_defaults(fn=cmd_board)
    with_company(sub.add_parser("approvals")).set_defaults(fn=cmd_approvals)

    sp = sub.add_parser("doctor", help="diagnose the installation")
    sp.add_argument("--quiet", action="store_true")
    sp.set_defaults(fn=cmd_doctor)

    sp = sub.add_parser("backup", help="zip the store and company configs")
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_backup)

    sp = sub.add_parser("ui", help="serve the operator console")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=cmd_ui)

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

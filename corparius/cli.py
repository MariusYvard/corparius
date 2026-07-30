"""Command line: init / run / status / approvals / approve / reject / rules / memory / inbox / claude / bench."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import company, paths
from .config import Settings, settings, setup_logging
from .store import Store
from .tools import TOOLS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _store() -> Store:
    """One construction point for the commands that open the store. Each CLI
    command is a short-lived, single-threaded process that exits right after, so
    unlike the console (see UiState.store) there is no connection to share or
    close - but keeping the construction in one place means a future argument or
    a pragma lands in exactly one spot.

    Settings() rather than the module-level `settings` snapshot. In a real run
    the two agree, because the snapshot is taken microseconds earlier at import.
    In a test they do not: the snapshot is taken at collection, before the
    hermetic fixture redirects CORP_DATA_PATH, so a test calling a cmd_* function
    wrote to the developer's own store. Resolving here is what keeps the CLI
    inside the same layering everything else obeys.
    """
    return Store(Settings().data_path)


def _company_path(slug_or_path: str) -> str:
    if os.path.isfile(slug_or_path):
        return slug_or_path
    # Route through the single company resolver so the CLI, console and MCP
    # server agree on where companies live (writable home, per-OS when frozen).
    return str(company.path_for(slug_or_path))


def _load_company(slug_or_path: str) -> dict:
    """Thin wrapper over company.load, keeping the CLI's exit-with-a-message
    ergonomics. The parsing, defaults and validation live in corparius/company.py so
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
    store = _store()
    store.save_state(cfg["slug"], {"tick": 0})
    on = [k for k, v in cfg.get("agents", {}).items() if v]
    print(f"initialised {cfg.get('name')} ({cfg['slug']}). agents on: {on}")


def cmd_run(args) -> None:
    from .orchestrator import Runtime

    cfg = _load_company(args.company)
    store = _store()
    result = Runtime(settings, store).run(cfg, ticks=args.ticks, loop=args.loop)
    print(json.dumps(result, indent=2))


def cmd_status(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    s = store.status(cfg["slug"])
    tick = store.load_state(cfg["slug"]).get("tick", 0)
    print(f"== {cfg.get('name')} ({cfg['slug']}) ==")
    print(f"clock: tick {tick}")
    print(
        f"actions: {s['actions']}  tokens: {s['tokens']}  "
        f"pending approvals: {s['pending_approvals']}"
    )
    for agent, n in sorted(s["by_agent"].items()):
        print(f"  {agent:12} {n}")


def cmd_site(args) -> None:
    from . import sitegen

    cfg = _load_company(args.company)
    out_dir = str(paths.site_dir(settings.data_path, cfg["slug"]))
    path = sitegen.build_site(cfg, out_dir, headline=args.headline or None, store=_store())
    print(f"sales site built: {path}")


def cmd_tasks(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    rows = store.list_tasks(cfg["slug"])
    if not rows:
        print("no tasks")
        return
    for t in rows:
        tool = t.get("tool") or "-"
        print(
            f"#{t['id']:<3} [{t['status']:<11}] p{t['priority']} {t['target']:<9} "
            f"{t['title']} [{tool}] (by {t['created_by']})"
        )


def cmd_task(args) -> None:
    store = _store()
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
    from . import deploy, sitegen

    cfg = _load_company(args.company)
    out_dir = str(paths.site_dir(settings.data_path, cfg["slug"]))
    if not os.path.exists(os.path.join(out_dir, "index.html")):
        sitegen.build_site(cfg, out_dir, store=_store())
    print("deployed: " + deploy.deploy_site(out_dir))


def cmd_repo(args) -> None:
    from . import companyrepo

    company = _load_company(args.company)
    slug = company["slug"]
    if args.status:
        print(f"== repo: {slug}")
        print(f"  local repository  {'yes' if companyrepo.is_repo(slug) else 'no'}")
        print(f"  remote            {companyrepo.remote_url(slug) or '(none)'}")
        print(f"  uncommitted       {'yes' if companyrepo.dirty(slug) else 'no'}")
        print(f"  autocommit        {'on' if companyrepo.autocommit_enabled() else 'off'}")
        available = [n for n, p in companyrepo.REGISTRY.items() if p.available()]
        print(f"  providers ready   {', '.join(available) or '(none)'}")
        return
    if args.sync:
        res = companyrepo.sync(slug, args.message or f"{slug}: manual sync")
        if not res["committed"]:
            print(res["error"] or "nothing to commit")
            return
        print("committed; " + ("pushed" if res["pushed"] else "not pushed: " + res["error"]))
        return
    print("repo: " + companyrepo.provision(slug, company.get("one_liner", "")))


def cmd_flow(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    fm = store.flow_metrics(cfg["slug"])
    print(f"== flow: {cfg.get('name')} ==")
    print(
        f"throughput(done): {fm['throughput']}   wip: {fm['wip']}   "
        f"tokens/task: {fm['tokens_per_completed_task']}   "
        f"bottleneck: {fm['bottleneck'] or 'none'}"
    )
    print(
        f"waste: {fm['defects']} defects (failed actions), "
        f"{fm['waiting']} waiting (pending approvals)"
    )
    for t, n in sorted(fm["by_target"].items()):
        print(f"  {t:12} {n} open")


def cmd_board(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    rows = store.list_tasks(cfg["slug"])
    print(f"== board: {cfg.get('name')} ==")
    for col in ("proposed", "approved", "in_progress", "waiting", "done", "rejected"):
        items = [t for t in rows if t["status"] == col]
        head = ", ".join(f"#{t['id']}:{t['target']}" for t in items[:6])
        print(f"{col:12} ({len(items)}): {head}")


def cmd_bench(args) -> None:
    """Measure what this machine can actually run locally.

    One real generation, timed by Ollama. It costs a few seconds — the load
    alone was 6.9s on the machine this was written for — which is why it lives
    behind a command instead of running wherever the answer is wanted.
    """
    from . import hardware

    settings = Settings()
    store = _store()
    models = hardware.installed_models()
    if not models:
        print("No local model installed, or Ollama is not reachable. Nothing to measure.")
        raise SystemExit(1)
    # Measure the model that would actually be used, not the smallest one:
    # a benchmark of something the company will never run answers nothing.
    from .llm import _split

    want = hardware.best_local_model(models, prefer=_split(settings.trivial_model)[1])
    spec = hardware.specs()
    result = hardware.measure(want or models[0]["name"])
    if not result["ok"]:
        print(result["detail"])
        raise SystemExit(1)
    hardware.profile_save(store, spec, result)
    choice, why = hardware.recommended_local(store, settings, models)
    if args.json:
        # The verdict, not only the numbers: a script that has to re-derive
        # "is this fast enough" from tokens_per_second will derive it
        # differently from the router, and then the two disagree.
        print(json.dumps({**spec, **result, "local_model": choice, "reason": why}, indent=2))
        return
    ram = f"{spec['ram_total'] / 1e9:.1f} GB" if spec["ram_total"] else "unknown"
    free = f"{spec['ram_available'] / 1e9:.1f} GB free" if spec["ram_available"] else "free unknown"
    print(f"machine: {spec['cores'] or '?'} cores, {ram} ({free})")
    print(
        f"{result['model']}: {result['tokens_per_second']} tokens/s "
        f"on the {result['placement'].upper()}, {result['load_seconds']}s to load"
    )
    choice, why = hardware.recommended_local(store, settings)
    print(f"\nlocal inference: {why}")
    if not choice:
        print("The trivial tier will go to a free provider instead.")


def cmd_claude(args) -> None:
    """Turn on the Claude subscription path, or test it.

    The console has had a one-press card for this since the beginning, but it
    lives in the Providers tab behind fourteen other providers, and an operator
    who drives corparius from a terminal never sees it. Four settings have to
    agree — mock off, cloud on, Claude Code on, and the tiers pointed at
    `claudecode:` — and that hidden conjunction is most of why this was hard to
    turn on. It is one command now, and literally the same plan the console
    applies — same connected providers, same measured local verdict.
    """
    from . import claudecli

    if getattr(args, "install", False) and not claudecli.installed():
        print(f"installing the Claude Code CLI: {claudecli.INSTALL_CMD}")
        print("this takes a minute...")
        done = claudecli.install()
        print(done["detail"])
        if not done["ok"]:
            raise SystemExit(1)
    result = claudecli.check()
    print(result["detail"])
    if args.check:
        return
    if not result["ok"]:
        print("\nnothing changed; fix the above, then run this again")
        raise SystemExit(1)
    # The same two inputs the console passes, or the two paths write different
    # plans from the same decision. This called plan() with no arguments, which
    # reads as "nothing free is connected" and puts every tier on the
    # subscription — the expensive default plan()'s own docstring warns about,
    # and it ignored --all-tiers into the bargain.
    from .hardware import recommended_local
    from .llm import connected_providers

    store = _store()
    local_trivial, _why = recommended_local(store, Settings())
    plan = claudecli.plan(connected_providers(), local_trivial, all_tiers=args.all_tiers)
    for key, value in plan.items():
        store.set_setting(key, value)
    every = all(v.startswith("claudecode:") for k, v in plan.items() if k.endswith("_MODEL"))
    print(
        "\nClaude Code is now serving every tier:"
        if every
        else "\nClaude Code now serves the hard tier; free providers keep the rest:"
    )
    for key, value in plan.items():
        print(f"  {key}={value}")
    print("\nNo API key, no credits: calls go through your subscription login.")


def cmd_update(args) -> None:
    """Replace this build with the newest release.

    Only from the downloadable binary; from source or Docker it says what to do
    instead. The download is checked against the published SHA256SUMS before
    anything moves, and a backup of the store and the companies is taken first
    even though an update cannot reach them.
    """
    from . import selfupdate, update_check

    blocked = selfupdate.why_not()
    if blocked:
        sys.exit(f"cannot update here: {blocked}")
    info = update_check.check()
    if not info.get("enabled"):
        print("The version check is off. Set CORP_UPDATE_CHECK=true to let corparius ask")
        print("GitHub once whether a newer release exists.")
        raise SystemExit(1)
    if not info.get("reachable"):
        sys.exit("could not reach GitHub to ask what the latest release is")
    if not info.get("update_available"):
        print(f"already on the newest release ({info['current']})")
        return
    tag = f"v{info['latest']}"
    if not args.yes:
        print(f"{info['current']} -> {info['latest']}")
        print("This downloads the new build, checks it against the published checksum")
        print("and replaces this program. Your companies and settings live in a separate")
        print("folder and are not touched; a backup is taken first anyway.")
        if input("continue? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("nothing was changed")
    try:
        done = selfupdate.apply(tag)
    except selfupdate.UpdateError as exc:
        sys.exit(str(exc))
    print(f"installed {done['installed']} at {done['path']}")
    if done["backup"]:
        print(f"backup: {done['backup']}")
    print(f"the build you were running is kept at {done['previous']} until the new one starts")
    print("start corparius again to run it")


def cmd_doctor(args) -> None:
    from .doctor import main as doctor_main

    sys.exit(doctor_main(quiet=args.quiet))


def cmd_backup(args) -> None:
    from . import backup

    path = backup.make_backup(settings.data_path, args.out, with_secrets=args.with_secrets)
    print(f"backup written: {path}")
    print(backup.describe(path, with_secrets=args.with_secrets))


def cmd_ui(args) -> None:
    from .webui import serve

    raise SystemExit(serve(settings, host=args.host, port=args.port))


def cmd_approvals(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    rows = store.list_approvals(cfg["slug"], "pending")
    if not rows:
        print("no pending approvals")
        return
    for r in rows:
        print(f"{r['id']}  {r['agent']:10} {r['tool']:26} {r['parameters']}")


def cmd_decide(args, status: str) -> None:
    cfg = _load_company(args.company)  # validates --company, exits with a message if wrong
    store = _store()
    approval = store.get_approval(args.id)
    ok = store.set_approval_status(args.id, status, args.note or "")
    if not ok:
        print("approval id not found")
        return
    print(f"{args.id} -> {status}")
    # Granted here rather than by a separate command: "yes, and stop asking" is
    # one decision, and splitting it in two invites the half that never runs.
    if getattr(args, "always", False) and status == "approved" and approval:
        from .permissions import PermissionEngine

        slug = approval["company"]
        tool = TOOLS.get(approval["tool"])
        engine = PermissionEngine.from_settings(Settings(), cfg, store)
        if tool is None or engine.evaluate(tool, slug).rule == "hitl":
            print(f"{approval['tool']} is gated by name; it keeps asking")
        else:
            store.add_rule(slug, approval["tool"], "always", "granted via CLI")
            print(f"standing rule added: {approval['tool']} no longer asks for {slug}")
    # Whatever decided it, a task parked on this approval can move again.
    freed = store.release_waiting_tasks(cfg["slug"])
    if freed["released"] or freed["refused"]:
        print(f"unblocked {freed['released']} task(s), refused {freed['refused']}")


def cmd_inbox(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
    if args.answer_to:
        if store.resolve_inbox(args.answer_to, args.answer):
            freed = store.release_waiting_tasks(cfg["slug"])
            print(f"answered {args.answer_to}; unblocked {freed['released']} task(s)")
        else:
            print("already answered, or no such item")
        return
    rows = store.list_inbox(cfg["slug"], "pending")
    print(f"== inbox: {cfg.get('name')} ==")
    for r in rows:
        print(f"[{r['kind']}] {r['id']}  {r['title']}")
        if r["body"]:
            print(f"    {r['body']}")
    if not rows:
        print("nothing waiting on you")


def cmd_memory(args) -> None:
    cfg = _load_company(args.company)
    store = _store()
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
    cfg = _load_company(args.company)
    store = _store()
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


def main(argv=None) -> None:
    setup_logging()
    from . import company, plugins

    plugins.load()  # no-op unless CORP_PLUGINS_ENABLED; extends the registries
    # Copy the bundled example into a fresh writable companies dir, the same
    # first-run seeding the frozen launcher does. Guarded: in a source checkout
    # the example already sits in companies/, so this is a stat and a return.
    company.seed_examples()
    p = argparse.ArgumentParser(prog="corparius", description="Run autonomous AI micro-companies.")
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

    sp = with_company(sub.add_parser("repo"))
    sp.add_argument(
        "--status", action="store_true", help="show the repository state, change nothing"
    )
    sp.add_argument("--sync", action="store_true", help="commit and push the company folder now")
    sp.add_argument("--message", default="", help="commit message for --sync")
    sp.set_defaults(fn=cmd_repo)

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

    sp = sub.add_parser("backup", help="zip the store, companies and settings")
    sp.add_argument(
        "--with-secrets",
        action="store_true",
        help="keep API keys in plaintext (a disaster-recovery copy; treat it like a password)",
    )
    sp.add_argument("--out", default=None)
    sp.set_defaults(fn=cmd_backup)

    sp = sub.add_parser("ui", help="serve the operator console")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=cmd_ui)

    sp = with_company(sub.add_parser("approve"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.add_argument(
        "--always",
        action="store_true",
        help="also stop asking about this tool for this company",
    )
    sp.set_defaults(fn=lambda a: cmd_decide(a, "approved"))

    sp = sub.add_parser("update", help="replace this build with the newest release")
    sp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    sp.set_defaults(fn=cmd_update)

    sp = sub.add_parser("bench", help="measure what this machine can run locally")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.set_defaults(fn=cmd_bench)

    sp = sub.add_parser("claude", help="use your Claude subscription, no API key")
    sp.add_argument(
        "--check", action="store_true", help="test the CLI login without changing any setting"
    )
    sp.add_argument(
        "--install",
        action="store_true",
        help="install the Claude Code CLI first if it is missing (npm, global)",
    )
    sp.add_argument(
        "--all-tiers",
        action="store_true",
        help="put every tier on the subscription, instead of only the hard one",
    )
    sp.set_defaults(fn=cmd_claude)

    sp = with_company(sub.add_parser("inbox"))
    sp.add_argument("--answer-to", default="", help="inbox item id to answer or dismiss")
    sp.add_argument("--answer", default="", help="the answer text")
    sp.set_defaults(fn=cmd_inbox)

    sp = with_company(sub.add_parser("memory"))
    sp.add_argument("--pin", type=int, default=0, help="memory id to pin")
    sp.add_argument("--forget", type=int, default=0, help="memory id to delete")
    sp.set_defaults(fn=cmd_memory)

    sp = with_company(sub.add_parser("rules"))
    sp.add_argument("--revoke", default="", help="tool name whose standing rule to drop")
    sp.set_defaults(fn=cmd_rules)

    sp = with_company(sub.add_parser("reject"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.set_defaults(fn=lambda a: cmd_decide(a, "rejected"))

    from . import appcli, plugincli, skillcli

    plugincli.add_parser(sub)
    skillcli.add_parser(sub)
    appcli.add_parser(sub)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

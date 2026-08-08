"""The work queue and the decisions on it. Rank 6.

`task` is the one to read twice. It called `store.update_task` directly, skipping the
validation the console did *and* the `executable_fields` call on approval — so approving from a
terminal left the task with no tool and it closed "done (no tool mapped)" having done nothing.
Measured on the real company: 24 tasks for one role, 22 of them closed that way. It goes
through `app_tasks.edit` now, and `tests/test_two_callers_agree.py` is what keeps it there.

`approve` and `reject` are one function with the decision bound at registration. Two parsers,
one code path, which is the point: a decision is a decision.
"""

from __future__ import annotations

from ..app.support import open_store
from ..config.settings import Settings
from ..tools.spec import SPEC
from . import support


def cmd_tasks(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
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
    """Edit a backlog task through the same service the console's backlog uses.

    It used to call `store.update_task(id, **fields)` directly, which meant it had none of the
    validation the console grew — and, worse, none of the `executable_fields` call on approval.
    Measured on a real store before this: the command line accepted `--target not-a-real-agent`
    and `--tool not-a-real-tool` and wrote both. And a task approved from here with no tool
    closed "done (no tool mapped)" having done nothing, so the condition survived and the agent
    proposed the same work again — 24 tasks for one role, 22 of them closed that way.
    """
    from ..app import errors as app_errors
    from ..app import tasks as app_tasks

    store = open_store()
    decision = "approved" if args.approve else "rejected" if args.reject else None
    try:
        changed = app_tasks.edit(
            store,
            args.id,
            title=args.title,
            priority=args.priority,
            target=args.target,
            tool=args.tool,
            decision=decision,
            note="via CLI",
        )
    except app_errors.Refused as exc:
        # The service raises the failure; the console turns it into a 400 and a terminal says it.
        print(exc)
        return
    said = ", ".join(changed["changed"]) or "nothing"
    print(f"task {changed['id']}: {said}" + (f" ({changed['decision']})" if decision else ""))


def cmd_approvals(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
    rows = store.list_approvals(cfg["slug"], "pending")
    if not rows:
        print("no pending approvals")
        return
    for r in rows:
        print(f"{r['id']}  {r['agent']:10} {r['tool']:26} {r['parameters']}")


def cmd_decide(args, status: str) -> None:
    cfg = support.load_company(args.company)  # validates --company, exits with a message if wrong
    store = open_store()
    approval = store.get_approval(args.id)
    ok = store.set_approval_status(args.id, status, args.note or "")
    if not ok:
        print("approval id not found")
        return
    print(f"{args.id} -> {status}")
    # Granted here rather than by a separate command: "yes, and stop asking" is
    # one decision, and splitting it in two invites the half that never runs.
    if getattr(args, "always", False) and status == "approved" and approval:
        from ..config.permissions import PermissionEngine

        slug = approval["company"]
        tool = SPEC.get(approval["tool"])
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
    cfg = support.load_company(args.company)
    store = open_store()
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


def register(sub) -> None:
    support.with_company(sub.add_parser("tasks")).set_defaults(fn=cmd_tasks)

    sp = support.with_company(sub.add_parser("task"))
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--title")
    sp.add_argument("--target")
    sp.add_argument("--tool")
    sp.add_argument("--priority", type=int)
    sp.add_argument("--approve", action="store_true")
    sp.add_argument("--reject", action="store_true")
    sp.set_defaults(fn=cmd_task)

    support.with_company(sub.add_parser("approvals")).set_defaults(fn=cmd_approvals)

    sp = support.with_company(sub.add_parser("approve"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.add_argument(
        "--always",
        action="store_true",
        help="also stop asking about this tool for this company",
    )
    sp.set_defaults(fn=lambda a: cmd_decide(a, "approved"))

    sp = support.with_company(sub.add_parser("reject"))
    sp.add_argument("--id", required=True)
    sp.add_argument("--note", default="")
    sp.set_defaults(fn=lambda a: cmd_decide(a, "rejected"))

    sp = support.with_company(sub.add_parser("inbox"))
    sp.add_argument("--answer-to", default="", help="inbox item id to answer or dismiss")
    sp.add_argument("--answer", default="", help="the answer text")
    sp.set_defaults(fn=cmd_inbox)

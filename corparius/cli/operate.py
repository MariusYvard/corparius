"""Running the company and asking it how it is doing. Rank 6.

`run` and `status`, the two commands an operator types most, plus the two views over the same
payload (`flow`, `board`) and the chat with the CEO. All five read or drive one company through
services in `app/`, which is why `status --json` prints exactly what the console's overview
card receives — the same function, not a second implementation of it.
"""

from __future__ import annotations

import json

from ..app.support import open_store
from ..config.settings import Settings
from . import support


def cmd_ceo(args) -> int:
    """Ask the CEO something, from a terminal.

    The console had this and a terminal did not, and the barrier was one line — the chat history
    lived in `UiState.chats`, a dict in the console's process. The service takes the history as a
    parameter now, so this passes a list and gets a single turn. That limit is stated rather than
    hidden: conversation that survives a process is a store table, not something a one-shot
    command can pretend to have.

    The CEO's powers come with it. Asked to pause a role or to focus the company, it acts and
    then says what it changed — the same `directives.apply` the console calls, so the sentence
    and the state agree here too.
    """
    from ..app import chat as app_chat

    cfg = support.load_company(args.company)
    # `Settings()` rather than the module-level snapshot, for the reason `open_store()` spells
    # out: the snapshot is taken at import, so it predates anything saved from the console —
    # and in a test it predates the fixture, which is how this reached the real network once.
    out = app_chat.once(open_store(), Settings(), cfg["slug"], args.message, lang=args.lang)
    print(out["reply"])
    if out["unanswered"]:
        return 1
    where = " / ".join(part for part in (out["provider"], out["model"]) if part)
    if where:
        print()
        print(f"-- {where}")
    if out["proposal"]:
        # The console renders this as a button. A terminal can only say what it would do, and
        # saying nothing would hide a decision the CEO is waiting on.
        print(f"-- it wants to: {out['proposal']['label']}")
    return 0


def cmd_run(args) -> None:
    from ..orchestrator import Runtime

    cfg = support.load_company(args.company)
    store = open_store()
    result = Runtime(Settings(), store).run(cfg, ticks=args.ticks, loop=args.loop)
    print(json.dumps(result, indent=2))


def cmd_status(args) -> int:
    """How the company is doing, through the same service the console polls.

    It printed four numbers — actions, tokens, pending approvals, a count per agent — and could
    not show **money spent**, the **flow** (work in progress, what is blocked, which role is the
    bottleneck), the session budget, or whether a run is going. An operator on a headless box had
    the cheapest half of what the product already knew about their company.

    Every field below was measured off a real payload rather than assumed. The first version of
    this function read `flow["done"]` and `status["cost"]`, neither of which exists — the shapes
    are `throughput` and a per-agent `spend_by_agent` list, and `cost_reported` is a separate
    boolean precisely because a provider reporting nothing must read as "not reported" and never
    as free.

    `--json` prints the whole payload, which is what a script wants and what the console gets.
    """
    from ..app import overview as app_overview

    cfg = support.load_company(args.company)
    store = open_store()
    data = app_overview.build(store, Settings(), cfg["slug"], company=cfg)
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0

    st, flow = data["status"], data["flow"]
    print(f"== {cfg.get('name')} ({cfg['slug']}) ==")
    print(f"clock: tick {data['tick']}" + ("  (a run is going)" if data.get("running") else ""))
    spent = sum(row["cost"] for row in data["spend_by_agent"])
    # "not reported" and "free" are different facts, and `cost_reported` exists so they cannot be
    # confused. A provider that says nothing about money must never read as costing nothing.
    money = f"{spent:.4f} EUR" if data.get("cost_reported") else "not reported"
    print(f"actions: {st['actions']}   tokens: {st['tokens']} of {data['session_budget']}")
    print(f"money:   {money}")
    print(
        f"flow:    {flow['wip']} in progress, {flow['waiting']} waiting, "
        f"{flow['throughput']} done"
        + (f"   bottleneck: {flow['bottleneck']}" if flow.get("bottleneck") else "")
    )
    if st["pending_approvals"]:
        print(f"waiting on you: {st['pending_approvals']} approval(s) — corparius approvals")
    if data.get("freezes"):
        print(f"the circuit breaker has frozen a day {data['freezes']} time(s)")
    tokens = {row["agent"]: row["t"] for row in data["spend_by_agent"]}
    for agent, n in sorted(st["by_agent"].items()):
        print(f"  {agent:12} {n:>4} actions  {tokens.get(agent, 0):>8} tokens")
    return 0


def cmd_flow(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
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
    cfg = support.load_company(args.company)
    store = open_store()
    rows = store.list_tasks(cfg["slug"])
    print(f"== board: {cfg.get('name')} ==")
    for col in ("proposed", "approved", "in_progress", "waiting", "done", "rejected"):
        items = [t for t in rows if t["status"] == col]
        head = ", ".join(f"#{t['id']}:{t['target']}" for t in items[:6])
        print(f"{col:12} ({len(items)}): {head}")


def register(sub) -> None:
    sp = support.with_company(sub.add_parser("run"))
    sp.add_argument("--ticks", type=int, default=6, help="simulated hours to run")
    sp.add_argument("--loop", action="store_true", help="keep running day after day")
    sp.set_defaults(fn=cmd_run)

    sp = support.with_company(sub.add_parser("status"))
    sp.add_argument("--json", action="store_true", help="the whole payload, as the console gets it")
    sp.set_defaults(fn=cmd_status)

    support.with_company(sub.add_parser("flow")).set_defaults(fn=cmd_flow)
    support.with_company(sub.add_parser("board")).set_defaults(fn=cmd_board)

    sp = support.with_company(
        sub.add_parser("ceo", help="ask the CEO something (the console chat)")
    )
    sp.add_argument("message", help="what to ask")
    sp.add_argument("--lang", default="en", help="the language the answer is written in")
    sp.set_defaults(fn=cmd_ceo)

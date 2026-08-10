"""Running the company and asking it how it is doing. Rank 6.

`run` and `status`, the two commands an operator types most, plus the two views over the same
payload (`flow`, `board`) and the chat with the CEO. All five read or drive one company through
services in `app/`, which is why `status --json` prints exactly what the console's overview
card receives — the same function, not a second implementation of it.
"""

from __future__ import annotations

import json

from ..app import runs as app_runs
from ..app.support import open_store
from ..config.settings import Settings
from . import support


def cmd_ceo(args) -> int:
    """Ask the CEO something, from a terminal.

    The console had this and a terminal did not, and the barrier was one line — the chat history
    lived in `UiState.chats`, a dict in the console's process. Then it was a parameter, and this
    passed a list and got a single turn with no memory of anything.

    **Schema 21 built the table this docstring used to point at.** Passing no history now means the
    stored conversation, so `corparius ceo` and the console are in the *same* thread: ask here, read
    the answer in the browser, and a phone sees both. The limit that was stated rather than hidden is
    simply gone.

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


def cmd_run(args) -> int:
    """Run in the foreground, and record it in `jobs` like any other run.

    Recorded because a run is a run whoever started it. Without the row, `corparius status` in
    another terminal — or the console, or a phone — would report "not running" while this process
    was mid-tick, which is the same phantom the v1 work removed from `/api/overview`. It also
    means this run can be stopped from anywhere: `should_stop` reads `cancel_requested`, and that
    is the whole cost of it.

    `running_job` is the guard, so two terminals cannot run the same company at once. That was
    never checked at all before; the console checked its own memory and the CLI checked nothing.
    """
    from ..orchestrator import Runtime
    from ..store import jobs as jobs_store

    cfg = support.load_company(args.company)
    store = open_store()
    slug = cfg["slug"]
    if store.running_job(app_runs.KIND, slug):
        print(f"a run is already in progress for {slug}")
        return 1
    job = store.start_job(
        app_runs.KIND,
        slug,
        progress="starting",
        params={"ticks": args.ticks, "loop": bool(args.loop)},
    )["id"]
    try:
        result = Runtime(Settings(), store).run(
            cfg,
            ticks=args.ticks,
            loop=args.loop,
            should_stop=lambda: store.cancel_requested(job),
        )
    except BaseException:
        # `BaseException`, so Ctrl-C on a `--loop` run does not leave the row saying `running`
        # forever — which the next process would then mark `interrupted`, true but a day late.
        store.finish_job(job, jobs_store.FAILED, {"error": "the run did not finish"})
        raise
    ended = jobs_store.CANCELLED if store.cancel_requested(job) else jobs_store.DONE
    store.finish_job(job, ended, result)
    print(json.dumps(result, indent=2))
    return 0


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
    # The run comes from `jobs` now, so a terminal sees a run the console started — and says
    # `interrupted` about one whose process went away instead of saying nothing.
    data = app_overview.build(
        store, Settings(), cfg["slug"], company=cfg, run=app_runs.view(store, cfg["slug"])
    )
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


def cmd_docs(args) -> None:
    """What the company has on file, from a terminal.

    A capability the console had and the command line did not — which is stage 6's own finding, still
    open here: measured before writing this, **no CLI module referenced `documents` at all.** So an
    operator on a headless box could not see that ten of their twelve files were sitting past the
    prompt budget, and could not read a brief their own design agent had written.

    `--read` and `--remove` and nothing else, and the omission is deliberate: **there is no `--add`.**
    Copying a file into the folder that `--list` prints is the upload, `load()` re-reads the directory
    on every call, and a file nothing can extract simply reports `no-extractor` in the listing. A
    command that shelled out to `cp` for the operator would be ceremony over a path they now have.

    The same `documents.inventory` the console reads, so the two cannot disagree about which files
    reach a prompt — the property `tests/test_two_callers_agree.py` exists to hold.
    """
    from .. import documents

    cfg = support.load_company(args.company)
    slug = cfg["slug"]

    if args.remove:
        try:
            moved = documents.remove(slug, args.remove)
        except documents.Refused as refused:
            print(f"{args.remove} was not removed: {refused.reason} {refused.detail}".rstrip())
            return
        print(f"moved out of the folder, kept at {moved.name}")
        return

    if args.read:
        doc = documents.full_text(slug, args.read)
        if doc is None:
            print(f"no document at {args.read}")
            return
        # The whole text, with no prompt budget applied. `MAX_CHARS` caps what an agent gets so a
        # thirty-page deck cannot swallow a turn; a person rereading their own brief wants the file.
        print(doc.text)
        return

    inv = documents.inventory(slug)
    print(f"== documents: {cfg.get('name')} ==")
    print(f"folder: {inv['folder']}")
    # The number that matters is not how many files exist, it is how many reach a prompt.
    print(
        f"{inv['total']} on file, {inv['reaching']} reach the agents, "
        f"{inv['used']} of {inv['budget']} characters used"
    )
    for doc in inv["documents"]:
        mark = "->" if doc["reaches"] else "  "
        origin = "written" if doc["written"] else "dropped"
        print(f"{mark} {doc['path']:44} {origin:8} {doc.get('reason') or ''}")
    if not inv["documents"]:
        print("nothing on file; copy a PDF, a deck or a note into the folder above")
    elif inv["total"] > len(inv["documents"]):
        print(f"{inv['total'] - len(inv['documents'])} more on file, not listed")


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
        sub.add_parser("docs", help="what the company has on file, and what reaches a prompt")
    )
    sp.add_argument("--read", default="", help="print one document's whole text")
    sp.add_argument("--remove", default="", help="move one document out of the folder")
    sp.set_defaults(fn=cmd_docs)

    sp = support.with_company(
        sub.add_parser("ceo", help="ask the CEO something (the console chat)")
    )
    sp.add_argument("message", help="what to ask")
    sp.add_argument("--lang", default="en", help="the language the answer is written in")
    sp.set_defaults(fn=cmd_ceo)

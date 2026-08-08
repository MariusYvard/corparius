"""Which companies exist: create one, stamp one, delete one, give one a repository. Rank 6.

Grouped by what the commands do rather than by the noun they act on — the whole package is —
and `lifecycle` is the honest word for four commands that bring a company into existence, mark
where it is, hand it a git remote and move it to the trash.
"""

from __future__ import annotations

from .. import company
from ..app.support import open_store
from . import support


def cmd_init(args) -> None:
    cfg = support.load_company(args.company)
    store = open_store()
    store.save_state(cfg["slug"], {"tick": 0})
    on = [k for k, v in cfg.get("agents", {}).items() if v]
    print(f"initialised {cfg.get('name')} ({cfg['slug']}). agents on: {on}")


def cmd_new(args) -> int:
    """Create a company from a terminal, through the console wizard's own validator.

    There was no way to do this before. `init` looks like it and is not — it stamps the state of
    a company that already exists — so an operator wrote companies/<slug>/company.yaml by hand,
    guessing the shape and the required fields, with nothing running `company.validate` at
    creation time. The wizard's design note is that a company created there and one edited later
    "can never disagree about what a company is"; a hand-written file had none of that.
    """
    from ..app import companies as app_companies
    from ..app import errors as app_errors

    if args.list_templates:
        for tpl in app_companies.templates(args.lang):
            agents = ", ".join(tpl["agents"]) or "the defaults"
            print(f"{tpl['id']:<12} {tpl['label']}")
            print(f"{'':<12} agents: {agents}")
        return 0
    try:
        out = app_companies.create(
            open_store(),
            name=args.name,
            one_liner=args.one_liner,
            product=args.product,
            segment=args.segment,
            template=args.template,
            session_tokens=args.session_tokens,
            lang=args.lang,
        )
    except app_errors.Refused as exc:
        print(exc)
        return 1
    print(f"created {out['config'].get('name')} ({out['slug']})")
    print(f"  {company.path_for(out['slug'])}")
    on = sorted(k for k, v in out["config"].get("agents", {}).items() if v)
    print(f"  agents on: {', '.join(on)}")
    for warning in out["warnings"]:
        print(f"  repaired: {warning}")
    print(f"next: corparius run --company {out['slug']} --ticks 12")
    return 0


def cmd_delete(args) -> int:
    """Move a company out of the way, and optionally purge what the store recorded about it.

    There was no way to do this from a terminal, so the obvious alternative was
    `rm -rf companies/<slug>` — which skips the trash *and* leaves every row the store holds
    about that company behind. Thirteen tables' worth, including its standing permissions: a new
    company created on the same slug would have inherited authorisations nobody granted it.

    The trash half destroys nothing. `--purge` is the half that cannot be undone, which is why
    it is a separate flag and why `--confirm` has to spell the slug — the same guard the
    console's dialog uses, because a destructive action reachable two ways must not be easier
    one of them.
    """
    from ..app import companies as app_companies
    from ..app import errors as app_errors

    cfg = support.load_company(args.company)
    slug = cfg["slug"]
    try:
        out = app_companies.delete(open_store(), slug, args.confirm, args.purge)
    except app_errors.Refused as exc:
        print(exc)
        if not args.confirm:
            print(f"pass --confirm {slug} to go ahead")
        return 1
    print(f"{slug} moved to {out['trashed']}")
    if not out["purged"]:
        print("the store still holds what it recorded; add --purge to drop that too")
        return 0
    for table, n in sorted(out["removed"].items()):
        print(f"  {table}: {n} row(s) removed")
    if not out["removed"]:
        print("  the store held nothing for it")
    return 0


def cmd_repo(args) -> None:
    from ..providers import companyrepo

    company = support.load_company(args.company)
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


def register(sub) -> None:
    # `new` first, because it is what an operator types before anything else exists. In the old
    # single `main()` it was registered twenty-fifth and `--help` listed it there.
    sp = sub.add_parser("new", help="create a company (the console wizard, from a terminal)")
    sp.add_argument("--name", default="", help="the company name; the slug is derived from it")
    sp.add_argument("--product", default="", help="what it sells, in one line")
    sp.add_argument("--segment", default="", help="who it sells to")
    sp.add_argument("--one-liner", dest="one_liner", default="")
    sp.add_argument("--template", default="", help="a starter template; --list-templates to see")
    sp.add_argument("--list-templates", action="store_true", help="show the templates and exit")
    sp.add_argument("--session-tokens", dest="session_tokens", type=int, default=80000)
    sp.add_argument("--lang", default="en", help="the language its examples are written in")
    sp.set_defaults(fn=cmd_new)

    support.with_company(sub.add_parser("init")).set_defaults(fn=cmd_init)

    sp = support.with_company(sub.add_parser("repo"))
    sp.add_argument(
        "--status", action="store_true", help="show the repository state, change nothing"
    )
    sp.add_argument("--sync", action="store_true", help="commit and push the company folder now")
    sp.add_argument("--message", default="", help="commit message for --sync")
    sp.set_defaults(fn=cmd_repo)

    sp = support.with_company(sub.add_parser("delete", help="move a company to companies/.trash/"))
    sp.add_argument("--confirm", default="", help="the slug again, to prove you meant this one")
    sp.add_argument(
        "--purge", action="store_true", help="also drop everything the store recorded about it"
    )
    sp.set_defaults(fn=cmd_delete)

"""Building the sales site and putting it somewhere. Rank 6.

The second live bug this restructuring found. `deploy` always built the generated path while
the console honoured `paths.owned_site(slug)`, so on the owner's own company the console
published `companies/vigil/site/public` and the command line published `data/sites/vigil` — and
said it worked, because `args.fn(args)` discarded the return value and the shell saw 0 either
way. Both are fixed: the resolution is `app_publish.resolve_folder` and `main()` returns the
exit code.
"""

from __future__ import annotations

from ..app.support import open_store
from ..config.settings import Settings
from ..kernel import paths
from . import support


def cmd_site(args) -> None:
    from .. import sitegen

    cfg = support.load_company(args.company)
    out_dir = str(paths.site_dir(Settings().data_path, cfg["slug"]))
    path = sitegen.build_site(cfg, out_dir, headline=args.headline or None, store=open_store())
    print(f"sales site built: {path}")


def cmd_deploy(args) -> int:
    """Publish through the same service the console uses.

    It used to build `paths.site_dir(data_path, slug)` itself and never consult
    `paths.owned_site`, so on a company with its own site folder — which is what an operator
    gets the moment they edit their pages instead of regenerating them — it published the
    generated site and said it worked. Measured on the owner's own company: the console
    published `companies/vigil/site/public` and this published `data/sites/vigil`.

    It also returned None either way, so a shell saw success whatever happened. A deploy that
    published nothing now exits non-zero.
    """
    from ..app import errors as app_errors
    from ..app import publish as app_publish

    cfg = support.load_company(args.company)
    try:
        out = app_publish.publish(cfg["slug"], Settings().data_path, cfg, open_store())
    except app_errors.Refused as exc:
        print(exc)
        return 1
    print(f"folder: {out['folder']}")
    if out["published"]:
        print(f"deployed: {out['provider']} -> {out['result']}")
        return 0
    for err in out["errors"]:
        print(f"  {err}")
    if out["skipped"]:
        print(f"  skipped (not configured): {', '.join(out['skipped'])}")
    print("nothing was published")
    return 1


def register(sub) -> None:
    sp = support.with_company(sub.add_parser("site"))
    sp.add_argument("--headline", default="", help="override the hero headline")
    sp.set_defaults(fn=cmd_site)

    support.with_company(sub.add_parser("deploy")).set_defaults(fn=cmd_deploy)

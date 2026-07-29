"""`corparius apps ...` — define, try and serve the company's own LLM apps.

An app is a YAML file in `companies/<slug>/apps/`. `run` works in mock mode, so
one is written and tried offline before it is exposed to anything. See
docs/apps.md.
"""

from __future__ import annotations

import json
import secrets
import sys
from typing import NoReturn

from . import apps as apps_mod


def _fail(msg: str) -> NoReturn:
    sys.exit(f"error: {msg}")


def _slug(args) -> str:
    slug = (getattr(args, "company", "") or "").strip()
    if not slug:
        _fail("name a company: --company <slug>")
    return slug


def _store():
    from .cli import _store as cli_store

    return cli_store()


def _company(slug: str) -> dict | None:
    from . import company as company_mod
    from . import paths

    path = paths.companies_dir() / slug / "company.yaml"
    try:
        return company_mod.load(path)
    except (FileNotFoundError, ValueError):
        # An app can run without it; it just answers about less.
        return None


def cmd_list(args) -> None:
    slug = _slug(args)
    found = apps_mod.load(slug)
    if not found:
        print(f"no apps for '{slug}'. Write one in companies/{slug}/apps/<name>.yaml")
        return
    for app in found:
        print(
            f"  {app.name:18} {app.tier.value:8} {app.max_tokens:>5} tok/call  "
            f"{app.daily_tokens:>7} tok/day  {app.rate_per_minute:>3}/min  "
            f"{'origins: ' + ', '.join(app.origins) if app.origins else 'NO origin list'}"
        )


def cmd_show(args) -> None:
    app = apps_mod.get(_slug(args), args.name)
    if app is None:
        _fail(f"no app named '{args.name}'")
    print(f"{app.name} — {app.description or 'no description'}")
    print(f"  file        {app.path}")
    print(f"  tier        {app.tier.value}")
    print(f"  per call    {app.max_tokens} tokens")
    print(f"  per day     {app.daily_tokens} tokens")
    print(f"  rate        {app.rate_per_minute} requests/minute per caller")
    print(
        f"  origins     {', '.join(app.origins) or 'none listed (the endpoint refuses browsers)'}"
    )
    print(f"\nsystem prompt:\n{app.system}")


def cmd_run(args) -> None:
    slug = _slug(args)
    app = apps_mod.get(slug, args.name)
    if app is None:
        _fail(f"no app named '{args.name}'")
    store = _store()
    spent = apps_mod.spent_today(store, slug, app)
    if spent >= app.daily_tokens:
        _fail(f"daily ceiling reached: {spent}/{app.daily_tokens} tokens today")
    result = apps_mod.run(app, slug, store, args.input, _company(slug))
    if args.json:
        print(json.dumps(result, indent=2))
        return
    if not result["ok"]:
        _fail(result["detail"])
    print(result["text"])
    usage = result["usage"]
    print(
        f"\n[{result['provider']}:{result['model']}] "
        f"{usage['input_tokens']}+{usage['output_tokens']} tokens, "
        f"{spent + usage['input_tokens'] + usage['output_tokens']}/{app.daily_tokens} today"
    )


def cmd_key(args) -> None:
    """Mint an app key.

    Deliberately printed with what it is not. Anything a browser sends is
    readable by whoever opens the inspector, so this identifies an app for
    accounting and revocation; the origin list, the rate limit and the daily
    ceiling are what actually hold.
    """
    slug = _slug(args)
    if apps_mod.get(slug, args.name) is None:
        _fail(f"no app named '{args.name}'")
    key = secrets.token_urlsafe(24)
    env = f"CORP_APP_KEY_{slug.upper().replace('-', '_')}_{args.name.upper().replace('-', '_')}"
    print(f"{env}={key}")
    print("\nPut that line in your .env, then restart the app server.")
    print(
        "This is NOT a secret once a web page sends it: anyone can read it in the\n"
        "inspector. It names the app so its spend is attributed and can be revoked.\n"
        "What protects the endpoint is the origin list, the rate limit and the daily\n"
        "ceiling in the app's YAML."
    )


def cmd_serve(args) -> None:
    from . import appserver, cfg

    if not cfg.get_bool("CORP_APPS_ENABLED"):
        _fail(
            "apps are off. Read docs/apps.md, then set CORP_APPS_ENABLED=true — this "
            "serves your LLM providers to whoever can reach the port."
        )
    sys.exit(appserver.serve(host=args.host, port=args.port))


def cmd_export(args) -> None:
    from . import appexport, paths
    from .config import Settings

    if args.target != "netlify":
        _fail(f"unknown export target '{args.target}'; only 'netlify' is supported")
    slug = _slug(args)
    settings = Settings()
    out = paths.site_dir(settings.data_path, slug)
    try:
        done = appexport.export(slug, args.name, out, settings)
    except appexport.ExportError as exc:
        _fail(str(exc))
    print(f"written: {done['path']}")
    print(f"  calls  {done['provider']}:{done['model']}")
    print(f"  needs  {done['key_env']} in the site's environment variables")
    print(
        "\nFrom here corparius no longer sees these calls. The key lives at the host,\n"
        "so the app's daily ceiling, its rate limit and its line in the company's cost\n"
        "breakdown do not apply to what this function spends. That is the price of a\n"
        "site that answers with nothing of yours left running."
    )


def add_parser(sub) -> None:
    """Wire the `apps` command and its sub-actions into the CLI."""
    pp = sub.add_parser("apps", help="the company's own LLM apps")
    psub = pp.add_subparsers(dest="apps_cmd", required=True)

    sp = psub.add_parser("list", help="what apps this company has, and their ceilings")
    sp.add_argument("--company", default="", help="company slug")
    sp.set_defaults(fn=cmd_list)

    sp = psub.add_parser("show", help="one app in full, including its system prompt")
    sp.add_argument("name")
    sp.add_argument("--company", default="")
    sp.set_defaults(fn=cmd_show)

    sp = psub.add_parser("run", help="call an app once from here (works in mock mode)")
    sp.add_argument("name")
    sp.add_argument("--company", default="")
    sp.add_argument("--input", required=True, help="what the caller would have sent")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_run)

    sp = psub.add_parser("key", help="mint the key that names an app to the endpoint")
    sp.add_argument("name")
    sp.add_argument("--company", default="")
    sp.set_defaults(fn=cmd_key)

    sp = psub.add_parser("serve", help="serve the apps endpoint (127.0.0.1 by default)")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=None)
    sp.set_defaults(fn=cmd_serve)

    sp = psub.add_parser("export", help="write the app as a function deployed with the site")
    sp.add_argument("target", nargs="?", default="netlify", choices=["netlify"])
    sp.add_argument("--app", dest="name", required=True)
    sp.add_argument("--company", default="")
    sp.set_defaults(fn=cmd_export)

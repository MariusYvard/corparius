"""`corparius plugin ...` — install and manage third-party plugins.

Verified plugins come from the curated registry (plugins/registry.json) and are
downloaded at a pinned ref and checked against a sha256. Installing an unverified
plugin from an arbitrary URL runs third-party code and is refused unless
CORP_PLUGINS_ALLOW_UNVERIFIED is set. See docs/plugins.md.
"""
from __future__ import annotations
import sys

from . import cfg, plugins


def _fail(msg: str) -> None:
    sys.exit(f"error: {msg}")


def cmd_list(args) -> None:
    st = plugins.status()
    if not st["enabled"]:
        print("plugins are OFF (set CORP_PLUGINS_ENABLED=true, then restart)\n")
    installed = st["installed"]
    if installed:
        print("installed:")
        for p in installed:
            flags = []
            flags.append("verified" if p["verified"] else "UNVERIFIED")
            if p["disabled"]:
                flags.append("disabled")
            if p["loaded"]:
                flags.append("loaded")
            print(f"  {p['name']:22} v{p['version']:8} [{', '.join(flags)}] {p['description']}")
    else:
        print("installed: none")
    reg = st["registry"]
    if reg:
        print("\navailable in the registry:")
        for e in reg:
            print(f"  {e.get('name',''):22} {e.get('description','')}")
        print("\ninstall one with: corparius plugin install <name>")


def cmd_info(args) -> None:
    entry = next((e for e in plugins.registry_entries() if e.get("name") == args.name), None)
    inst = next((p for p in plugins.status()["installed"] if p["name"] == args.name), None)
    if not entry and not inst:
        _fail(f"unknown plugin '{args.name}'")
    if entry:
        print(f"registry: {entry.get('name')} — {entry.get('description','')}")
        print(f"  repo: {entry.get('repo','')}  ref: {entry.get('ref','')}")
        print(f"  kinds: {', '.join(entry.get('kinds', []))}")
    if inst:
        print(f"installed: v{inst['version']}  "
              f"{'verified' if inst['verified'] else 'UNVERIFIED'}"
              f"{', disabled' if inst['disabled'] else ''}"
              f"{', loaded' if inst['loaded'] else ''}")


def cmd_install(args) -> None:
    try:
        if args.url:
            print("WARNING: installing an UNVERIFIED plugin runs third-party code you "
                  "have not audited.")
            path = plugins.install_from_url(args.url, args.name)
        else:
            path = plugins.install_from_registry(args.name)
    except plugins.PluginError as exc:
        _fail(str(exc))
    print(f"installed to {path}")
    if not cfg.get_bool("CORP_PLUGINS_ENABLED"):
        print("plugins are off; enable them with CORP_PLUGINS_ENABLED=true, then restart.")
    else:
        print("restart corparius to activate it.")


def cmd_enable(args) -> None:
    try:
        plugins.set_enabled(args.name, True)
    except plugins.PluginError as exc:
        _fail(str(exc))
    print(f"enabled '{args.name}' (restart to apply)")


def cmd_disable(args) -> None:
    try:
        plugins.set_enabled(args.name, False)
    except plugins.PluginError as exc:
        _fail(str(exc))
    print(f"disabled '{args.name}' (restart to apply)")


def cmd_remove(args) -> None:
    try:
        plugins.remove(args.name)
    except plugins.PluginError as exc:
        _fail(str(exc))
    print(f"removed '{args.name}'")


def add_parser(sub) -> None:
    """Wire the `plugin` command and its sub-actions into the CLI."""
    pp = sub.add_parser("plugin", help="install and manage plugins")
    psub = pp.add_subparsers(dest="plugin_cmd", required=True)

    psub.add_parser("list", help="list installed and available plugins").set_defaults(fn=cmd_list)

    sp = psub.add_parser("info", help="show a plugin's details")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_info)

    sp = psub.add_parser("install", help="install a verified plugin (or --url for unverified)")
    sp.add_argument("name", help="registry name, or the name to install --url under")
    sp.add_argument("--url", help="install an UNVERIFIED plugin from a .tar.gz URL")
    sp.set_defaults(fn=cmd_install)

    for action, fn in (("enable", cmd_enable), ("disable", cmd_disable), ("remove", cmd_remove)):
        sp = psub.add_parser(action, help=f"{action} an installed plugin")
        sp.add_argument("name")
        sp.set_defaults(fn=fn)

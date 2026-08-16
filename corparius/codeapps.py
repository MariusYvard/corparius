"""A program a company owns, written by its own coder and run on this machine. Rank 4.

`apps.py` holds the other kind: a prompt, a tier and its ceilings, which corparius answers itself
through the router. That covers a FAQ and a form that understands a sentence, and it covers nothing
that has to *compute* — a demo that scores a recording, an endpoint the site posts to, a tool the
company uses internally.

Until now the coder role could not produce either. `generate_code` asked a model to "describe a small
feature in one sentence" and returned that sentence; `publish_production_code` returned the string
`"Merged PR #42 to production (mock)"`, the same number for every company on every day. There was no
folder for source, no language, and nothing that runs. This is the folder, the manifest and the
bounds.

## The shape

    companies/<slug>/code/<name>/
        app.yaml        what it is and how to start it
        main.py         whatever the coder wrote
        ...

`app.yaml` is small on purpose, and every field in it is something corparius has to know rather than
something a program might like to declare:

    name: demo-vocal
    language: python          python | node | command
    entry: main.py            the file, or the command for `language: command`
    port: 8770                what it listens on; corparius passes it as $PORT too
    description: ...          one line, shown to the operator

## What bounds it

Model-written code running with an operator's rights is the risk this carries, and it is stated
rather than hidden. What is enforced:

  * **loopback only** — the port is checked on 127.0.0.1 and the site is given that address, so
    nothing here is reachable from another machine;
  * **a lifetime** — `MAX_LIFETIME_S` after which it is stopped, because a program that leaks is a
    program that leaks slowly and a company runs unattended for days;
  * **one at a time per app**, tracked by pid, so a run that restarts does not leave the old one
    holding the port;
  * **an environment with no credentials in it** — every `CORP_*` and every name reading like a
    key, a token, a secret or a password is removed before the child sees it. A program that needs
    one has to be given it deliberately.

What is **not** enforced, and saying so is the point: memory and disk are not capped. `resource`
does it on POSIX and Windows needs a Job Object, and a bound that exists on one platform is a bound
an operator would believe on all three. The lifetime and the stop button are what there is.

## Why the language is the company's choice and the runtime is not

Python is guaranteed — corparius runs on it, so a company can always ship one. Node is used if it is
installed and refused clearly if it is not, rather than failing at the first import. `command` is the
escape hatch for anything else, and it is the operator's decision rather than the model's: a manifest
naming an arbitrary command is a manifest that runs an arbitrary command.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .kernel import paths
from .kernel import text as textkit

log = logging.getLogger("corparius.codeapps")

MANIFEST = "app.yaml"
LANGUAGES = ("python", "node", "command")
# The bounds a *manifest* is measured against. How long a program may live and how long it has to
# open its port are the runner's, in `providers/apprunner`, because they are facts about supervising
# a process rather than about what an app is.
PORT_FLOOR = 8770
PORT_CEILING = 8820
# **How many programs one company may own, and it is a real ceiling rather than a formality.**
#
# Nothing bounded this at first, and the failure it invites is specific: a model asked every day to
# write an app has no memory of the name it chose yesterday, so it invents `demo`, `demo-v2`,
# `retour-vocal`, `retour-vocal-2` — a folder and a process and a port each, forever, against fifty
# ports. Six is more than any company here has needed and small enough that the seventh is a
# decision somebody makes rather than a drift nobody notices.
MAX_APPS = 6
# What one app's log may reach before the oldest half goes. A program that logs a line per request
# writes without limit otherwise, and the useful part of a log is always the end of it.
MAX_LOG_BYTES = 512 * 1024


@dataclass
class CodeApp:
    name: str
    language: str
    entry: str
    port: int
    description: str = ""
    folder: Path = field(default_factory=Path)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "language": self.language,
            "entry": self.entry,
            "port": self.port,
            "description": self.description,
            "url": self.url,
        }


def code_dir(slug: str) -> Path:
    return paths.companies_dir() / (slug or "company") / "code"


def _port_for(slug: str, name: str, taken: set[int] | None = None) -> int:
    """A stable port per app, derived rather than assigned.

    Derived so the same app gets the same address every launch: the sales page holds that address in
    its markup, and a port that moved on restart would mean rebuilding the page on restart.

    **`hashlib`, not `hash()`**, and the difference is the whole point. Python randomises `hash()`
    per process, so the first version of this handed an app a different port every time corparius
    started — the exact opposite of what the sentence above claims. Within one process it looks
    perfectly stable, so it took the full suite to show it: two tests passed alone and failed
    together, which is what a collision between two randomly-placed ports looks like.

    `taken` is the linear probe. Two names can land on one slot however good the hash is, and a
    second app silently failing to bind is a worse answer than the next free number.
    """
    taken = taken or set()
    digest = hashlib.md5(f"{slug}/{name}".encode()).digest()
    span = PORT_CEILING - PORT_FLOOR
    start = int.from_bytes(digest[:4], "big") % span
    for step in range(span):
        port = PORT_FLOOR + (start + step) % span
        if port not in taken:
            return port
    return PORT_FLOOR + start


def next_port(slug: str, name: str) -> int:
    """The address this app should be given, once, at the moment it is created.

    Settled here rather than derived on every read, and that distinction cost a broken suite to
    find. Probing past what its siblings hold means the answer depends on which siblings exist — so
    deriving it again on each `load` let a seventh app move the address of the second, while the
    sales page still carried the old one in its markup. Written into the manifest instead: derived
    once, stable however many arrive after it.
    """
    taken = {app.port for app in load(slug) if app.name != textkit.slugify(name)}
    return _port_for(slug, name, taken)


def parse(folder: Path, slug: str = "") -> CodeApp | None:
    """Read one app's manifest, or None with a line saying why.

    Never raises: this is called over a glob of a folder an agent writes into, and one malformed
    manifest must cost that app and not the listing.
    """
    path = folder / MANIFEST
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("code app %s: %s", folder.name, exc)
        return None
    if not isinstance(raw, dict):
        log.warning("code app %s: %s is not a mapping", folder.name, MANIFEST)
        return None
    name = textkit.slugify(str(raw.get("name") or folder.name))
    language = str(raw.get("language") or "python").strip().lower()
    if language not in LANGUAGES:
        log.warning("code app %s: unknown language %r", name, language)
        return None
    entry = str(raw.get("entry") or "").strip()
    if not entry:
        log.warning("code app %s: no entry to run", name)
        return None
    try:
        port = int(raw.get("port"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # Derived when the manifest does not say. An agent writing its first app should not have to
        # pick a free port, and one that picks 80 should not be obeyed.
        port = _port_for(slug, name)
    if not PORT_FLOOR <= port < PORT_CEILING:
        port = _port_for(slug, name)
    return CodeApp(
        name=name,
        language=language,
        entry=entry,
        port=port,
        description=" ".join(str(raw.get("description") or "").split())[:200],
        folder=folder,
    )


def load(slug: str) -> list[CodeApp]:
    """Every app this company has written, by name."""
    root = code_dir(slug)
    if not root.is_dir():
        return []
    apps = [
        app
        for app in (
            parse(child, slug) for child in sorted(root.iterdir()) if (child / MANIFEST).is_file()
        )
        if app is not None
    ]
    return apps


def get(slug: str, name: str) -> CodeApp | None:
    wanted = textkit.slugify(str(name or ""))
    return next((app for app in load(slug) if app.name == wanted), None)


def command_for(app: CodeApp) -> tuple[list[str], str]:
    """What to run, or ("", why not).

    `sys.executable` rather than `python`, so an app runs on the interpreter corparius runs on
    instead of whatever a PATH happens to offer — which on Windows is often a store stub that opens
    a shop page.
    """
    import sys

    if app.language == "python":
        return [sys.executable, app.entry], ""
    if app.language == "node":
        node = shutil.which("node")
        if not node:
            return [], "node is not installed on this machine, so this app cannot start"
        return [node, app.entry], ""
    parts = app.entry.split()
    if not parts:
        return [], "the manifest names no command to run"
    if not shutil.which(parts[0]):
        return [], f"{parts[0]} is not on PATH"
    return parts, ""


# What a program written by a model must never be handed. A **deny list**, and the first version was
# an allow list of four variables — `PATH`, `PORT`, `PYTHONUNBUFFERED`, `SYSTEMROOT` — which passed
# here and failed every macOS job in CI: the child started, wrote nothing at all to its log, and
# never bound its port. An interpreter needs more of its environment than four names on some
# platforms, and guessing which four is a guess that has to be right on three operating systems.
#
# Denying is the shape that achieves the same thing without that bet: the promise was never "four
# variables", it was "no credentials", and this states exactly that.
SECRET_MARKERS = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASS", "_CREDENTIAL")


def child_env(app: CodeApp) -> dict:
    """The machine's environment, minus everything that is a credential, plus `PORT`.

    A model wrote this program, so the environment is the cheapest place to be strict — and the
    promise being kept is **no credentials**, not "four variables". Stated that way because the first
    version was the other way: an allow list of `PATH`, `PORT`, `PYTHONUNBUFFERED` and `SYSTEMROOT`,
    which worked on Windows, passed here, and failed every macOS job in CI with a child that started,
    wrote nothing to its log and never bound its port. Guessing which four variables an interpreter
    needs is a guess that has to be right on three operating systems.

    So: every `CORP_*`, and every name that reads like a key, a token, a secret or a password, is
    removed. What is left is what the operating system needs to run a program, which is the thing
    that cannot be enumerated portably.
    """
    safe = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("CORP_")
        and not any(marker in name.upper() for marker in SECRET_MARKERS)
    }
    return {**safe, "PORT": str(app.port), "PYTHONUNBUFFERED": "1"}


def key(slug: str, name: str) -> str:
    """How the runner tracks one app. Built here because the runner does not know what a company is."""
    return f"{slug}/{name}"


def launch(slug: str, name: str) -> dict:
    """Start one of this company's programs and wait for it to answer.

    The domain half of the job: find the app, work out the command, decide what it may see of the
    machine, and hand a rank-3 supervisor four host-shaped arguments. `apprunner` knows nothing about
    companies, which is what lets a test drive it with a two-line script.
    """
    from .providers import apprunner

    app = get(slug, name)
    if app is None:
        return {"ok": False, "running": False, "error": f"no app called {name!r}"}
    cmd, refusal = command_for(app)
    if refusal:
        return {"ok": False, "running": False, "error": refusal}
    # Before the launch, because the file is not open for writing then — which matters on Windows,
    # where a handle held by a running child makes it unwritable.
    trim_log(app.folder / "app.log")
    out = apprunner.start(
        key(slug, name),
        cmd,
        cwd=str(app.folder),
        log_file=str(app.folder / "app.log"),
        port=app.port,
        env=child_env(app),
    )
    return {**out, "url": app.url} if out.get("ok") else out


def halt(slug: str, name: str) -> dict:
    from .providers import apprunner

    return apprunner.stop(key(slug, name))


def status(slug: str, name: str) -> dict:
    """What this app is doing, without starting or stopping anything."""
    from .providers import apprunner

    app = get(slug, name)
    if app is None:
        return {"name": name, "exists": False, "running": False, "error": "no such app"}
    live = apprunner.running(key(slug, name))
    return {
        **app.as_dict(),
        "exists": True,
        "running": live,
        "answering": apprunner.listening(app.port) if live else False,
        "pid": apprunner.pid(key(slug, name)),
        "seconds": apprunner.uptime(key(slug, name)),
        "log": str(app.folder / "app.log"),
    }


def statuses(slug: str) -> list[dict]:
    """Every app this company has, and what each is doing. What the console renders."""
    return [status(slug, app.name) for app in load(slug)]


def room_for(slug: str, name: str) -> str:
    """ "" if this company may write `name`, or the reason it may not.

    Replacing one it already has is always allowed — a company improving its own program is the
    normal case and must never be the thing that hits a ceiling. What is refused is the seventh
    *new* one, because a model asked daily to write an app does not remember what it called
    yesterday's and will keep inventing names until the ports run out.
    """
    have = load(slug)
    if any(app.name == textkit.slugify(name) for app in have):
        return ""
    if len(have) >= MAX_APPS:
        return (
            f"{slug} already has {len(have)} programs ({', '.join(a.name for a in have)}) and "
            f"{MAX_APPS} is the limit. Improve one of those instead, or delete one first."
        )
    return ""


def trim_log(path: Path, limit: int = MAX_LOG_BYTES) -> bool:
    """Keep the newest half of a log that has grown past `limit`. True when it was trimmed.

    Halving rather than emptying: a program that fails at start writes its traceback and nothing
    else, and truncating on the way past the limit would throw away the only thing anybody reads.
    Called before a launch rather than on a timer, because that is the moment the file is not open
    for writing on Windows.
    """
    try:
        if not path.is_file() or path.stat().st_size <= limit:
            return False
        keep = path.read_bytes()[-(limit // 2) :]
        path.write_bytes(b"[earlier lines dropped: this log passed its size limit]\n" + keep)
        return True
    except OSError as exc:
        log.info("could not trim %s (%s)", path, exc)
        return False

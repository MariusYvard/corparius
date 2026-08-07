"""Publishing a company's site through the deploy chain. Rank 5.

**Another live bug from having two callers**, and a worse one than the backlog's. Measured on
the owner's real company:

    console publishes  companies/vigil/site/public    the operator's own site
    CLI publishes      data/sites/vigil               the generated one

`webui._deploy` honours `paths.owned_site(slug)` — the company's own site folder wins, "exactly
as it does for the agent's deploy tool", because the console publishing a different folder than
the roster does would be the worst of both. `cli.cmd_deploy` never learned that: it always built
`paths.site_dir(data_path, slug)`. So on any company with its own site — which is what an
operator gets the moment they edit their pages rather than regenerate them — the command line
published the wrong thing and said it worked.

It also reported success at the shell level either way, because it printed a line and returned
None. A deploy that published nothing now leaves a non-zero exit code, which is what a script
around it needs.

One resolver, one chain, one answer. `Refused` for a company that is not there; the console
maps it to a 404 and a terminal prints it.
"""

from __future__ import annotations

from pathlib import Path

from ..kernel import paths
from ..providers import deploy as deploy_provider
from .errors import Refused


def resolve_folder(slug: str, data_path: str, company: dict, store=None) -> str:
    """Which folder actually gets published, building the generated one if it is the answer.

    Separated from `publish` because it is the half that was wrong in one caller, and because
    "what would you publish" is a question worth being able to ask without publishing.
    """
    owned = paths.owned_site(slug)
    if owned is not None:
        return str(owned)
    out_dir = paths.site_dir(data_path, slug)
    if not paths.site_index(data_path, slug).exists():
        from ..sitegen import build_site

        build_site(company, str(out_dir), store=store)
    return str(out_dir)


def publish(slug: str, data_path: str, company: dict | None, store=None) -> dict:
    """Publish, and report what happened rather than whether the call returned.

    `deploy_result` rather than `deploy_site`: the structured answer carries `ok`, the provider
    that took it, the errors from the ones that did not, and what was skipped. A formatter over
    it is fine for a terminal; a caller deciding anything needs the fields.
    """
    if not company:
        raise Refused(f"unknown company '{slug}'")
    out_dir = resolve_folder(slug, data_path, company, store)
    res = deploy_provider.deploy_result(out_dir)
    if res["ok"]:
        # Remember where it went, so the "go live" card shows the live URL again after a reload
        # and not only in the response that published it.
        try:
            (Path(out_dir) / ".published").write_text(str(res["result"]), encoding="utf-8")
        except OSError:
            pass
    return {
        "folder": out_dir,
        "published": res["ok"],
        "provider": res["provider"],
        "result": res["result"],
        "errors": res["errors"],
        "skipped": res["skipped"],
    }

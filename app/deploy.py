"""Site deployment across interchangeable providers, tried in order with
fallback, so a company never depends on a single host. The local provider is
always available and needs nothing external. The others activate only when
configured, and any one can be first: set CORP_DEPLOY_PROVIDERS to reorder.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod

from . import cfg, paths


class DeployProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def deploy(self, site_dir: str) -> str: ...


class LocalDirProvider(DeployProvider):
    """Publish to a local web root (self-hosted nginx or Caddy) or a data
    folder. Always available, zero external dependency."""

    name = "local"

    def available(self) -> bool:
        return True

    def deploy(self, site_dir: str) -> str:
        dest = cfg.get("CORP_DEPLOY_LOCAL_DIR", "").strip() or paths.published_dir(site_dir)
        os.makedirs(dest, exist_ok=True)
        for entry in os.listdir(site_dir):
            src = os.path.join(site_dir, entry)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dest, entry))
        return f"local:{dest}"


class NetlifyProvider(DeployProvider):
    """Deploy via the Netlify CLI. Needs the `netlify` binary and a token."""

    name = "netlify"

    def available(self) -> bool:
        return bool(shutil.which("netlify")) and bool(cfg.get("NETLIFY_AUTH_TOKEN"))

    def deploy(self, site_dir: str) -> str:
        cmd = ["netlify", "deploy", "--dir", site_dir, "--prod"]
        site = cfg.get("NETLIFY_SITE_ID", "")
        if site:
            cmd += ["--site", site]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "netlify deploy failed")
        return "netlify:prod"


class S3Provider(DeployProvider):
    """Any S3-compatible endpoint: AWS S3, self-hosted MinIO, Cloudflare R2.
    Set CORP_S3_ENDPOINT to point away from AWS."""

    name = "s3"

    def available(self) -> bool:
        if not cfg.get("CORP_S3_BUCKET"):
            return False
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False
        return True

    def deploy(self, site_dir: str) -> str:
        import boto3

        bucket = cfg.get("CORP_S3_BUCKET")
        if not bucket:
            raise RuntimeError("CORP_S3_BUCKET is not set")
        s3 = boto3.client(
            "s3",
            endpoint_url=cfg.get("CORP_S3_ENDPOINT") or None,
            aws_access_key_id=cfg.get("CORP_S3_KEY"),
            aws_secret_access_key=cfg.get("CORP_S3_SECRET"),
            region_name=cfg.get("CORP_S3_REGION"),
        )
        for entry in os.listdir(site_dir):
            src = os.path.join(site_dir, entry)
            if os.path.isfile(src):
                ctype = "text/html" if entry.endswith(".html") else "application/octet-stream"
                s3.upload_file(src, bucket, entry, ExtraArgs={"ContentType": ctype})
        return f"s3:{bucket}"


class SSHProvider(DeployProvider):
    """rsync to a self-hosted server (a VPS or a homelab box running nginx).
    Set CORP_DEPLOY_SSH_TARGET, e.g. user@host:/var/www/site."""

    name = "ssh"

    def available(self) -> bool:
        return bool(shutil.which("rsync")) and bool(cfg.get("CORP_DEPLOY_SSH_TARGET"))

    def deploy(self, site_dir: str) -> str:
        target = cfg.get("CORP_DEPLOY_SSH_TARGET")
        if not target:
            raise RuntimeError("CORP_DEPLOY_SSH_TARGET is not set")
        out = subprocess.run(
            ["rsync", "-az", site_dir.rstrip("/\\") + "/", target],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "rsync failed")
        return f"ssh:{target}"


REGISTRY: dict[str, DeployProvider] = {
    p.name: p for p in [LocalDirProvider(), NetlifyProvider(), S3Provider(), SSHProvider()]
}


def _order() -> list[str]:
    raw = cfg.get("CORP_DEPLOY_PROVIDERS", "local,netlify,s3,ssh")
    return [x.strip() for x in raw.split(",") if x.strip()]


def deploy_result(site_dir: str) -> dict:
    """Try each configured provider in order and say plainly whether anything
    published.

    deploy_site() below returns a string either way, which meant a total failure
    came back looking exactly like a success and was logged as one. Callers that
    need to know use this.
    """
    errors: list[str] = []
    skipped: list[str] = []
    for name in _order():
        provider = REGISTRY.get(name)
        if provider is None:
            skipped.append(f"{name}: unknown provider")
            continue
        if not provider.available():
            skipped.append(f"{name}: not configured")
            continue
        try:
            return {
                "ok": True,
                "provider": name,
                "result": provider.deploy(site_dir),
                "errors": errors,
                "skipped": skipped,
            }
        except Exception as exc:  # fall through to the next provider on failure
            errors.append(f"{name}: {exc}")
    return {"ok": False, "provider": "", "result": "", "errors": errors, "skipped": skipped}


def deploy_site(site_dir: str) -> str:
    """The human-readable line. A formatter over deploy_result; kept because the
    CLI prints it and the tools log it."""
    res = deploy_result(site_dir)
    if res["ok"]:
        return f"{res['provider']} -> {res['result']}"
    if res["errors"]:
        return "no provider succeeded (" + "; ".join(res["errors"]) + ")"
    return "no provider available"

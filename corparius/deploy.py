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

import requests

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
    """Deploy to Netlify over its API: a token, no CLI, no local install.

    This is the simplest public-hosting path. `available()` is true as soon as a
    token is set - the earlier version needed the `netlify` binary on PATH, which
    was the friction. The first publish creates a site (Netlify assigns a free
    subdomain) and the id is remembered next to the built site, so later publishes
    reuse it. Returns the live URL.

    The digest deploy protocol: declare every file by its sha1, Netlify replies
    with the subset it does not already have, upload those, and the deploy goes
    live. All over `requests` - no new dependency.
    """

    name = "netlify"
    API = "https://api.netlify.com/api/v1"

    def available(self) -> bool:
        return bool(cfg.get("NETLIFY_AUTH_TOKEN", "").strip())

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {cfg.get('NETLIFY_AUTH_TOKEN', '').strip()}"}

    def _resolve_site(self, site_dir: str) -> tuple[str, dict | None]:
        """Return (site_id, created_site). An explicit NETLIFY_SITE_ID wins; then
        the id remembered from a previous publish; otherwise create a new site."""
        explicit = cfg.get("NETLIFY_SITE_ID", "").strip()
        if explicit:
            return explicit, None
        marker = os.path.join(site_dir, ".netlify-site-id")
        if os.path.isfile(marker):
            with open(marker, encoding="utf-8") as fh:
                remembered = fh.read().strip()
            if remembered:
                return remembered, None
        r = requests.post(f"{self.API}/sites", headers=self._headers(), timeout=30)
        r.raise_for_status()
        site = r.json()
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(site["id"])
        return site["id"], site

    def deploy(self, site_dir: str) -> str:
        import hashlib

        site_id, created = self._resolve_site(site_dir)
        files: dict[str, str] = {}
        blobs: dict[str, tuple[str, bytes]] = {}
        for entry in sorted(os.listdir(site_dir)):
            full = os.path.join(site_dir, entry)
            if os.path.isfile(full) and not entry.startswith("."):
                with open(full, "rb") as fh:
                    data = fh.read()
                sha = hashlib.sha1(data).hexdigest()  # noqa: S324 - Netlify's digest, not security
                files["/" + entry] = sha
                blobs[sha] = (entry, data)
        r = requests.post(
            f"{self.API}/sites/{site_id}/deploys",
            headers=self._headers(),
            json={"files": files},
            timeout=30,
        )
        r.raise_for_status()
        dep = r.json()
        for sha in dep.get("required", []):
            entry, data = blobs[sha]
            up = requests.put(
                f"{self.API}/deploys/{dep['id']}/files/{entry}",
                headers={**self._headers(), "Content-Type": "application/octet-stream"},
                data=data,
                timeout=120,
            )
            up.raise_for_status()
        url = dep.get("ssl_url") or dep.get("url") or (created or {}).get("ssl_url", "")
        if not url:  # older deploy payloads omit the url; ask the site
            s = requests.get(f"{self.API}/sites/{site_id}", headers=self._headers(), timeout=30)
            if s.ok:
                url = s.json().get("ssl_url", "")
        return f"netlify:{url or site_id}"


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

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


class DeployProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def deploy(self, site_dir: str) -> str:
        ...


class LocalDirProvider(DeployProvider):
    """Publish to a local web root (self-hosted nginx or Caddy) or a data
    folder. Always available, zero external dependency."""

    name = "local"

    def available(self) -> bool:
        return True

    def deploy(self, site_dir: str) -> str:
        dest = os.environ.get("CORP_DEPLOY_LOCAL_DIR", "").strip()
        if not dest:
            dest = os.path.join(os.path.dirname(site_dir.rstrip("/\\")), "published")
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
        return bool(shutil.which("netlify")) and bool(os.environ.get("NETLIFY_AUTH_TOKEN"))

    def deploy(self, site_dir: str) -> str:
        cmd = ["netlify", "deploy", "--dir", site_dir, "--prod"]
        site = os.environ.get("NETLIFY_SITE_ID", "")
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
        if not os.environ.get("CORP_S3_BUCKET"):
            return False
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False
        return True

    def deploy(self, site_dir: str) -> str:
        import boto3
        bucket = os.environ["CORP_S3_BUCKET"]
        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get("CORP_S3_ENDPOINT") or None,
            aws_access_key_id=os.environ.get("CORP_S3_KEY"),
            aws_secret_access_key=os.environ.get("CORP_S3_SECRET"),
            region_name=os.environ.get("CORP_S3_REGION"),
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
        return bool(shutil.which("rsync")) and bool(os.environ.get("CORP_DEPLOY_SSH_TARGET"))

    def deploy(self, site_dir: str) -> str:
        target = os.environ["CORP_DEPLOY_SSH_TARGET"]
        out = subprocess.run(["rsync", "-az", site_dir.rstrip("/\\") + "/", target],
                             capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "rsync failed")
        return f"ssh:{target}"


REGISTRY: dict[str, DeployProvider] = {
    p.name: p for p in [LocalDirProvider(), NetlifyProvider(), S3Provider(), SSHProvider()]
}


def _order() -> list[str]:
    raw = os.environ.get("CORP_DEPLOY_PROVIDERS", "local,netlify,s3,ssh")
    return [x.strip() for x in raw.split(",") if x.strip()]


def deploy_site(site_dir: str) -> str:
    """Try each configured provider in order; return "name -> result" on the
    first that works. The local provider is always available, so unless it is
    removed from the order this never hard-fails."""
    errors = []
    for name in _order():
        provider = REGISTRY.get(name)
        if provider is None or not provider.available():
            continue
        try:
            return f"{name} -> {provider.deploy(site_dir)}"
        except Exception as exc:   # fall through to the next provider on failure
            errors.append(f"{name}: {exc}")
    return "no provider succeeded (" + "; ".join(errors) + ")" if errors else "no provider available"

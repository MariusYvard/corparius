"""Deployment must never depend on one host: the chain falls back to a local,
self-hosted target that is always available."""
from app import deploy
from app.deploy import LocalDirProvider


def test_local_provider_is_always_available():
    assert LocalDirProvider().available() is True


def test_chain_falls_back_to_local(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    dest = tmp_path / "published"
    monkeypatch.setenv("CORP_DEPLOY_LOCAL_DIR", str(dest))
    # Externals listed first, but none are configured, so local must win.
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh,local")
    result = deploy.deploy_site(str(site))
    assert result.startswith("local -> local:")
    assert (dest / "index.html").exists()


def test_reports_when_no_provider_is_available(tmp_path, monkeypatch):
    site = tmp_path / "s"
    site.mkdir()
    for var in ("NETLIFY_AUTH_TOKEN", "CORP_S3_BUCKET", "CORP_DEPLOY_SSH_TARGET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh")   # local removed
    assert "no provider available" in deploy.deploy_site(str(site))

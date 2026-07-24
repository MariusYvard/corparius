"""Deployment must never depend on one host: the chain falls back to a local,
self-hosted target that is always available."""

from corparius import cfg, deploy
from corparius.deploy import LocalDirProvider, NetlifyProvider


def test_local_provider_is_always_available():
    assert LocalDirProvider().available() is True


class _FakeResp:
    def __init__(self, payload=None, ok=True):
        self._payload = payload or {}
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def test_netlify_available_on_token_alone_no_cli(monkeypatch):
    """The whole point of the API path: a token is enough, no `netlify` binary."""
    monkeypatch.setenv("NETLIFY_AUTH_TOKEN", "nfp_x")
    cfg.invalidate()
    assert NetlifyProvider().available() is True
    monkeypatch.delenv("NETLIFY_AUTH_TOKEN")
    cfg.invalidate()
    assert NetlifyProvider().available() is False


def test_netlify_creates_a_site_then_uploads_and_returns_url(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html>hi</html>", encoding="utf-8")
    monkeypatch.setenv("NETLIFY_AUTH_TOKEN", "nfp_x")
    monkeypatch.delenv("NETLIFY_SITE_ID", raising=False)
    cfg.invalidate()

    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url))
        if url.endswith("/sites"):
            return _FakeResp({"id": "site123", "ssl_url": "https://demo.netlify.app"})
        if url.endswith("/deploys"):
            # Netlify asks for every declared sha (none cached yet).
            return _FakeResp(
                {
                    "id": "dep1",
                    "required": list(json["files"].values()),
                    "ssl_url": "https://demo.netlify.app",
                }
            )
        raise AssertionError(url)

    puts = []

    def fake_put(url, headers=None, data=None, timeout=None):
        puts.append(url)
        return _FakeResp({})

    monkeypatch.setattr(deploy.requests, "post", fake_post)
    monkeypatch.setattr(deploy.requests, "put", fake_put)

    result = NetlifyProvider().deploy(str(site))
    assert result == "netlify:https://demo.netlify.app"
    # A site was created and the id remembered for next time.
    assert (site / ".netlify-site-id").read_text(encoding="utf-8") == "site123"
    assert any(u.endswith("/sites") for _, u in calls)
    assert any("/sites/site123/deploys" in u for _, u in calls)
    assert len(puts) == 1 and puts[0].endswith("/deploys/dep1/files/index.html")


def test_netlify_reuses_the_remembered_site(tmp_path, monkeypatch):
    """A second publish must not spawn a second Netlify site."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    (site / ".netlify-site-id").write_text("siteABC", encoding="utf-8")
    monkeypatch.setenv("NETLIFY_AUTH_TOKEN", "nfp_x")
    monkeypatch.delenv("NETLIFY_SITE_ID", raising=False)
    cfg.invalidate()

    posted = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posted.append(url)
        assert not url.endswith("/sites"), "must not create a new site"
        return _FakeResp({"id": "dep2", "required": [], "ssl_url": "https://demo.netlify.app"})

    monkeypatch.setattr(deploy.requests, "post", fake_post)
    result = NetlifyProvider().deploy(str(site))
    assert result == "netlify:https://demo.netlify.app"
    assert posted == ["https://api.netlify.com/api/v1/sites/siteABC/deploys"]


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
    monkeypatch.setenv("CORP_DEPLOY_PROVIDERS", "netlify,s3,ssh")  # local removed
    assert "no provider available" in deploy.deploy_site(str(site))

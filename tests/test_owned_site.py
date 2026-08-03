"""A company that ships its own site publishes that site, and the publish is checked.

Both mechanisms are reverse-engineered from the NanoCorp worker logs; see
docs/reverse-engineering/nanocorp.md.

**The site.** Measured on the owner's own install: `companies/vigil/site/` held
six hand-built HTML pages, a stylesheet, a serverless function, robots.txt and
sitemap.xml, versioned in the company's own git repository. Corparius could not
see any of it. `build_sales_site` regenerated a single page from four fields of
`company.yaml` under `data/sites/vigil/`, every design turn, and reported "Sales
site built"; `deploy_site` published *that*. The operator asked why their site
was still bad, and the answer was that the product had never touched their site.

**The check.** `deploy_site` reported `Site published: netlify -> <url>` on the
provider's word and never fetched the address. NanoCorp's worker does the
opposite, and its log shows what that is worth: on one task the push succeeded,
the route was deployed, and production answered with an error because the host
did not have the API key. One bounded wait, one check, report either way.
"""

import requests

from corparius import paths, sitecheck


def _site(base, name="public", pages=("index.html",), toml=None):
    folder = base / "site" / name
    folder.mkdir(parents=True)
    for page in pages:
        (folder / page).write_text(f"<title>{page}</title>", encoding="utf-8")
    if toml is not None:
        (base / "site" / "netlify.toml").write_text(toml, encoding="utf-8")
    return folder


# --- which folder is the site ------------------------------------------------


def test_a_company_with_no_site_of_its_own_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    (tmp_path / "plain").mkdir()
    assert paths.owned_site("plain") is None


def test_netlify_publish_key_decides(tmp_path, monkeypatch):
    """A company that wrote `publish = "public"` has already said which folder is
    the site. Publishing the root instead would push its netlify.toml and its
    serverless sources to the web."""
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    base = tmp_path / "c"
    wanted = _site(base, "public", toml='[build]\n  publish = "public"\n')
    (base / "site" / "netlify").mkdir()
    (base / "site" / "netlify" / "functions").mkdir()
    assert paths.owned_site("c") == wanted


def test_a_conventional_folder_is_found_without_a_toml(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    for name in ("dist", "build", "_site"):
        base = tmp_path / name
        assert paths.owned_site(name) is None
        wanted = _site(base, name)
        assert paths.owned_site(name) == wanted


def test_html_at_the_root_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    base = tmp_path / "flat" / "site"
    base.mkdir(parents=True)
    (base / "index.html").write_text("<title>flat</title>", encoding="utf-8")
    assert paths.owned_site("flat") == base


def test_a_site_folder_with_nothing_publishable_is_not_a_site(tmp_path, monkeypatch):
    """An empty folder, or one holding only sources, must not become the deploy
    target — publishing it would replace a working site with nothing."""
    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    base = tmp_path / "src" / "site"
    (base / "netlify" / "functions").mkdir(parents=True)
    (base / "README.md").write_text("notes", encoding="utf-8")
    assert paths.owned_site("src") is None


# --- and every path that acts on a site agrees --------------------------------


def test_the_generator_refuses_to_overwrite_a_real_site(tmp_path, monkeypatch):
    from corparius import tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _site(tmp_path / "c", pages=("index.html", "tech.html", "beta.html"))

    class Ctx:
        company = {"slug": "c", "name": "C"}
        data_path = str(tmp_path / "data")
        store = None

    out = tools._build_site(Ctx(), "A headline")
    assert "its own site" in out
    assert "3 page(s)" in out and "tech.html" in out
    assert not (tmp_path / "data" / "sites").exists(), "it generated a competing page anyway"


def test_the_deploy_tool_publishes_the_companys_own_site(tmp_path, monkeypatch):
    from corparius import deploy, tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    wanted = _site(tmp_path / "c", pages=("index.html", "tech.html"))
    published: list[str] = []
    monkeypatch.setattr(
        deploy,
        "deploy_result",
        lambda site_dir: (
            published.append(site_dir)
            or {
                "ok": True,
                "provider": "netlify",
                "result": "https://x",
                "errors": [],
                "skipped": [],
            }
        ),
    )
    monkeypatch.setattr(
        sitecheck, "verify", lambda *a, **k: {"state": sitecheck.UNVERIFIED, "detail": "no url"}
    )

    class Ctx:
        company = {"slug": "c", "name": "C"}
        data_path = str(tmp_path / "data")
        store = None

    res = tools._deploy_site(Ctx())
    assert res.ok and "its own site" in res.output
    assert published == [str(wanted)], f"it published {published}, not the company's site"


def test_the_console_previews_the_same_site_it_would_publish(tmp_path, monkeypatch):
    """A preview showing one page while the deploy pushes another is the worst of
    both: the operator approves what they were shown."""
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _site(tmp_path / "c", pages=("index.html",))
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])

    class Ctx:
        slug = "c"
        path = "/site/c/"

    code, body = webui._route_site_get(Ctx())[:2]
    assert code == 200 and body["built"] is True and body["owned"] is True
    code, served, _ = webui._route_site_serve(Ctx())
    assert code == 200 and b"index.html" in served


# --- one check, and it says what it measured ---------------------------------


def test_nothing_is_claimed_without_an_address(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("it called out"))
    )
    out = sitecheck.verify("", "<title>x</title>")
    assert out["state"] == sitecheck.UNVERIFIED and out["measured"] is False
    assert "nothing was verified" in sitecheck.line(out)


def test_the_published_title_on_the_live_page_reads_fresh(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _Resp(200, "<html><title>Vigil — check-in</title></html>"),
    )
    out = sitecheck.verify("https://x.fr", "<title>Vigil — check-in</title>", wait=0)
    assert out["state"] == sitecheck.FRESH and out["measured"] is True
    assert "Verified live" in sitecheck.line(out)


def test_a_different_title_reads_stale_rather_than_published(monkeypatch):
    """This is the case the whole module exists for: the provider accepted the
    upload and the address serves something else."""
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, "<title>Old page</title>"))
    out = sitecheck.verify("https://x.fr", "<title>New page</title>", wait=0)
    assert out["state"] == sitecheck.STALE
    assert "cached build" in out["detail"] and "not live yet" in sitecheck.line(out)


def test_an_error_page_is_not_a_publish(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(404, "<title>Not found</title>"))
    out = sitecheck.verify("https://x.fr", "<title>New</title>", wait=0)
    assert out["state"] == sitecheck.UNREACHABLE and out["status"] == 404


def test_a_host_that_does_not_answer_is_named(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("name or service not known")

    monkeypatch.setattr(requests, "get", boom)
    out = sitecheck.verify("https://x.fr", "<title>New</title>", wait=0)
    assert out["state"] == sitecheck.UNREACHABLE and "ConnectionError" in out["detail"]


def test_it_looks_exactly_once(monkeypatch):
    """One check, then stop either way. A loop of reloads against a CDN teaches
    nothing and spends the turn — NanoCorp's worker says so in its own log."""
    calls = []
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: calls.append(1) or _Resp(200, "<title>Old</title>")
    )
    sitecheck.verify("https://x.fr", "<title>New</title>", wait=0)
    assert len(calls) == 1


def test_the_wait_is_bounded(monkeypatch):
    monkeypatch.setenv("CORP_DEPLOY_VERIFY_WAIT", "99999")
    assert sitecheck.wait_seconds() == sitecheck.MAX_WAIT
    monkeypatch.setenv("CORP_DEPLOY_VERIFY_WAIT", "-5")
    assert sitecheck.wait_seconds() == 0


def test_the_marker_is_the_title_not_a_hash():
    """A generated page carries a build timestamp, so a byte hash differs on every
    build and every check would read stale."""
    assert sitecheck.marker_of("<title>  Vigil\n  — x </title>") == "Vigil — x"
    assert sitecheck.marker_of("<html>no title</html>") == ""


class _Resp:
    def __init__(self, status, text, content_type="text/html; charset=utf-8"):
        self.status_code = status
        self.text = text
        self.headers = {"content-type": content_type}


# --- what must not go live ---------------------------------------------------


def test_a_marker_left_for_a_human_stops_the_publish(tmp_path):
    (tmp_path / "index.html").write_text(
        "<title>x</title><p>Écrivez à REMPLACER@TON-DOMAINE.fr</p>", encoding="utf-8"
    )
    found = sitecheck.placeholders(tmp_path)
    assert any("REMPLACER" in f for f in found) and any("TON-DOMAINE" in f for f in found)
    assert all("index.html" in f for f in found)


def test_the_count_is_real(tmp_path):
    (tmp_path / "a.html").write_text("FIXME FIXME FIXME", encoding="utf-8")
    assert sitecheck.placeholders(tmp_path) == ["a.html: FIXME (3x)"]


def test_a_clean_site_says_nothing(tmp_path):
    (tmp_path / "index.html").write_text(
        "<title>Vigil</title><p>90 secondes.</p>", encoding="utf-8"
    )
    (tmp_path / "robots.txt").write_text("Sitemap: https://vigil.fr/sitemap.xml", encoding="utf-8")
    assert sitecheck.placeholders(tmp_path, "https://vigil.fr") == []


def test_the_xml_namespace_is_not_a_finding(tmp_path):
    """The first version of this reported `www.sitemaps.org` — the namespace, which
    is in every sitemap ever written. A detector that cries wolf is a detector
    somebody switches off, and this one was caught by running it against a real
    site rather than by reading it back."""
    (tmp_path / "sitemap.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "  <url><loc>https://vigil.fr/</loc></url>\n"
        "</urlset>\n",
        encoding="utf-8",
    )
    assert sitecheck.placeholders(tmp_path, "https://vigil.fr") == []


def test_a_sitemap_pointing_at_another_host_is_a_finding(tmp_path):
    """robots.txt and sitemap.xml are read as authority. Pointing them at a host
    the site is not published at tells a crawler to index somebody else — the same
    reasoning sitegen already applies to the canonical link."""
    (tmp_path / "sitemap.xml").write_text(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://old-domain.fr/</loc></url></urlset>",
        encoding="utf-8",
    )
    (tmp_path / "robots.txt").write_text(
        "User-agent: *\nSitemap: https://old-domain.fr/sitemap.xml\n", encoding="utf-8"
    )
    found = sitecheck.placeholders(tmp_path, "https://vigil.fr")
    assert len(found) == 2
    assert all("old-domain.fr" in f and "vigil.fr" in f for f in found)


def test_prose_mentioning_a_domain_is_left_alone(tmp_path):
    """A blog post naming a competitor's site is not a defect. Only the two files a
    crawler obeys are compared."""
    (tmp_path / "blog.html").write_text(
        "<title>b</title><p>Voir https://autre-site.fr pour comparer.</p>", encoding="utf-8"
    )
    assert sitecheck.placeholders(tmp_path, "https://vigil.fr") == []


def test_no_site_url_means_no_host_comparison(tmp_path):
    """Nothing to compare against is not a finding. Guessing the intended host
    would be the invention this whole check exists to prevent."""
    (tmp_path / "robots.txt").write_text("Sitemap: https://anything.fr/s.xml", encoding="utf-8")
    assert sitecheck.placeholders(tmp_path, "") == []


def test_the_deploy_refuses_rather_than_publishing_placeholders(tmp_path, monkeypatch):
    from corparius import deploy, tools
    from corparius.store import Store

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    folder = _site(tmp_path / "c", pages=("index.html",))
    (folder / "index.html").write_text("<title>x</title>REMPLACER@TON-DOMAINE.fr", encoding="utf-8")
    monkeypatch.setattr(
        deploy, "deploy_result", lambda d: (_ for _ in ()).throw(AssertionError("it published"))
    )
    store = Store(str(tmp_path / "data"))

    class Ctx:
        company = {"slug": "c", "name": "C", "site": {"url": "https://c.fr"}}
        data_path = str(tmp_path / "data")

    ctx = Ctx()
    ctx.store = store
    try:
        res = tools._deploy_site(ctx)
        assert res.ok is False
        assert "placeholder" in res.output and "REMPLACER" in res.output
        # And it says so where the operator reads it, not only in the action log.
        titles = [i["title"] for i in store.list_inbox("c", "pending")]
        assert "The site still carries placeholders" in titles
    finally:
        store.close()

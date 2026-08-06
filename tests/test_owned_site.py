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

from corparius import sitecheck
from corparius.kernel import paths


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
    from corparius.tools import effects as tools

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
    from corparius import deploy
    from corparius.tools import effects as tools

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
    from corparius import deploy
    from corparius.store import Store
    from corparius.tools import effects as tools

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


# --- the preview serves a site, not a page ------------------------------------


def _served(slug, path):
    from corparius import webui

    class Ctx:
        pass

    ctx = Ctx()
    ctx.path = f"/site/{slug}{path}"
    return webui._route_site_serve(ctx)


def test_the_preview_serves_the_stylesheet(tmp_path, monkeypatch):
    """It used to serve index.html and nothing else, which was fine while the site
    *was* one generated page. For a company that ships its own, every
    /assets/style.css came back 404 — so the preview rendered the operator's real
    copy in Times New Roman with blue underlined links. They sent a screenshot of it
    and reasonably read it as the site being broken."""
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    folder = _site(tmp_path / "c", pages=("index.html", "tech.html"))
    (folder / "assets").mkdir()
    (folder / "assets" / "style.css").write_text("body{color:red}", encoding="utf-8")

    code, body, kind = _served("c", "/assets/style.css")
    assert (code, kind) == (200, "text/css") and b"color:red" in body


def test_the_preview_serves_the_other_pages_and_folders(tmp_path, monkeypatch):
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    folder = _site(tmp_path / "c", pages=("index.html", "tech.html"))
    (folder / "blog").mkdir()
    (folder / "blog" / "index.html").write_text("<title>blog</title>", encoding="utf-8")

    assert _served("c", "/tech.html")[0] == 200
    assert _served("c", "/blog/")[0] == 200, "a directory must resolve to its index"
    assert b"blog" in _served("c", "/blog/")[1]
    assert _served("c", "/")[0] == 200, "the root must resolve to index.html"


def test_the_preview_refuses_to_leave_the_site_folder(tmp_path, monkeypatch):
    """The company folder holds its config, its skills and its migration notes next
    to the site. Checked on the resolved path, not on the text of the URL."""
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    _site(tmp_path / "c", pages=("index.html",))
    (tmp_path / "c" / "company.yaml").write_text("slug: c\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")

    for attempt in (
        "/../company.yaml",
        "/../../.env",
        "/%2e%2e/%2e%2e/.env",
        "/assets/../../company.yaml",
    ):
        code, body = _served("c", attempt)[:2]
        assert code == 404, f"{attempt} was served"
        assert b"SECRET" not in (body if isinstance(body, bytes) else b"")


def test_only_the_declared_types_are_served(tmp_path, monkeypatch):
    """The preview is not a general file server. A .py or a .yaml inside the site
    folder is a source file, not a page."""
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    folder = _site(tmp_path / "c", pages=("index.html",))
    (folder / "build.py").write_text("print(1)", encoding="utf-8")
    (folder / "config.yaml").write_text("k: v", encoding="utf-8")

    assert _served("c", "/build.py")[0] == 404
    assert _served("c", "/config.yaml")[0] == 404
    assert ".py" not in webui.SITE_TYPES and ".yaml" not in webui.SITE_TYPES


def test_an_unknown_company_is_refused_before_any_path_is_built(tmp_path, monkeypatch):
    from corparius import webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    assert _served("nosuch", "/index.html")[0] == 404


def test_a_generated_page_still_previews(tmp_path, monkeypatch):
    """The company with no site of its own has not changed."""
    from corparius import sitegen, webui

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    monkeypatch.setattr(webui, "_companies", lambda: ["c"])
    (tmp_path / "c").mkdir()
    data = tmp_path / "data"
    sitegen.build_site(
        {"slug": "c", "name": "C", "offer": {"product": "p"}}, str(data / "sites" / "c")
    )
    monkeypatch.setattr(webui, "_fresh_settings", lambda: type("S", (), {"data_path": str(data)})())
    assert _served("c", "/")[0] == 200


# --- the address a publish returns --------------------------------------------


def _company(base, slug="c", site=None):
    (base / slug).mkdir(parents=True, exist_ok=True)
    text = f"slug: {slug}\nname: C\noffer:\n  product: p\nicp:\n  segment: s\n  pains: [x]\n"
    if site:
        text += "site:\n" + "".join(f"  {k}: {v}\n" for k, v in site.items())
    (base / slug / "company.yaml").write_text(text, encoding="utf-8")


def test_the_published_address_fills_an_empty_site_url(tmp_path, monkeypatch):
    """`site.url` is the one SEO fact the generator cannot work out for itself, and
    the operator cannot know it before the first publish — Netlify assigns it. The
    provider already returned it and nothing read it back: data that arrives and is
    thrown away, one more time."""
    from corparius import company as cm
    from corparius.tools import effects as tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _company(tmp_path)
    said = tools._record_site_url("c", "netlify:https://vigil-abc123.netlify.app")
    assert "https://vigil-abc123.netlify.app" in said
    assert cm.load(cm.path_for("c"), "c")["site"]["url"] == "https://vigil-abc123.netlify.app"


def test_a_domain_the_operator_chose_is_never_overwritten(tmp_path, monkeypatch):
    """They decided. Replacing it with whatever the last deploy answered would take
    the last word away from the person running the business."""
    from corparius import company as cm
    from corparius.tools import effects as tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _company(tmp_path, site={"url": "https://vigil.fr"})
    assert tools._record_site_url("c", "netlify:https://other.netlify.app") == ""
    assert cm.load(cm.path_for("c"), "c")["site"]["url"] == "https://vigil.fr"


def test_a_result_with_no_address_records_nothing(tmp_path, monkeypatch):
    """The local provider returns a filesystem path. Writing that into site.url
    would put `/data/sites/published` in a canonical link."""
    from corparius import company as cm
    from corparius.tools import effects as tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _company(tmp_path)
    assert tools._record_site_url("c", "local:/data/sites/published") == ""
    assert tools._record_site_url("c", "ssh:deploy@host:/var/www") == ""
    assert not (cm.load(cm.path_for("c"), "c").get("site") or {}).get("url")


def test_a_missing_company_does_not_fail_the_publish(tmp_path, monkeypatch):
    from corparius.tools import effects as tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    assert tools._record_site_url("nosuch", "netlify:https://x.netlify.app") == ""


# --- the crawler files follow the real address ---------------------------------


def _pages(folder, robots=None, noindex=()):
    for name in ("index.html", "tech.html", "merci.html"):
        head = '<meta name="robots" content="noindex">' if name in noindex else ""
        (folder / name).write_text(
            f"<html><head><title>{name}</title>{head}"
            f'<link rel="canonical" href="https://old-host.fr/{name}"></head></html>',
            encoding="utf-8",
        )
    if robots is not None:
        (folder / "robots.txt").write_text(robots, encoding="utf-8")


def test_the_sitemap_lists_the_pages_that_exist(tmp_path):
    from corparius import sitegen

    _pages(tmp_path)
    out = sitegen.companions_for_folder(tmp_path, "https://vigil-abc.netlify.app/")
    assert "<loc>https://vigil-abc.netlify.app/</loc>" in out["sitemap.xml"]
    assert "<loc>https://vigil-abc.netlify.app/tech.html</loc>" in out["sitemap.xml"]


def test_nothing_is_written_without_an_address(tmp_path):
    """The same line sitegen has always drawn: an absolute tag is omitted rather than
    pointed at a guess, because a canonical link to the wrong address is worse for a
    site than no canonical link at all."""
    from corparius import sitegen

    _pages(tmp_path)
    assert sitegen.companions_for_folder(tmp_path, "") == {}
    assert sitegen.point_absolute_tags(tmp_path, "") == 0


def test_a_page_the_site_keeps_out_of_the_index_is_not_in_the_sitemap(tmp_path):
    """Measured: `merci.html` is noindex and disallowed in robots.txt, and the first
    version of this listed it anyway. A sitemap that contradicts the robots.txt beside
    it is a defect a crawler reports back."""
    from corparius import sitegen

    _pages(tmp_path, robots="User-agent: *\nDisallow: /merci.html\n", noindex=("merci.html",))
    out = sitegen.companions_for_folder(tmp_path, "https://x.fr")
    assert "merci.html" not in out["sitemap.xml"]
    assert "tech.html" in out["sitemap.xml"]


def test_the_operators_robots_policy_is_preserved(tmp_path):
    """Regenerating the file would have deleted a real decision: the owner's
    robots.txt allows GPTBot, ClaudeBot, PerplexityBot and Google-Extended with a
    comment explaining why. Overwriting that to fix a hostname would be the product
    throwing away their SEO policy."""
    from corparius import sitegen

    policy = (
        "User-agent: *\nAllow: /\nDisallow: /merci.html\n\n"
        "# Generative engines: allowed, on purpose.\n"
        "User-agent: GPTBot\nAllow: /\n\n"
        "User-agent: ClaudeBot\nAllow: /\n\n"
        "Sitemap: https://old-host.fr/sitemap.xml\n"
    )
    _pages(tmp_path, robots=policy)
    out = sitegen.companions_for_folder(tmp_path, "https://vigil-abc.netlify.app")["robots.txt"]
    assert "GPTBot" in out and "ClaudeBot" in out
    assert "on purpose" in out, "the comment explaining the decision is part of it"
    assert "Disallow: /merci.html" in out
    assert out.count("Sitemap:") == 1, "the stale line has to go, not be joined"
    assert "https://vigil-abc.netlify.app/sitemap.xml" in out and "old-host.fr" not in out


def test_a_site_with_no_robots_gets_a_plain_one(tmp_path):
    from corparius import sitegen

    _pages(tmp_path)
    out = sitegen.companions_for_folder(tmp_path, "https://x.fr")["robots.txt"]
    assert out.startswith("User-agent: *") and "Sitemap: https://x.fr/sitemap.xml" in out


def test_the_absolute_tags_are_pointed_at_the_real_host(tmp_path):
    from corparius import sitegen

    _pages(tmp_path)
    (tmp_path / "index.html").write_text(
        '<link rel="canonical" href="https://old-host.fr/">'
        '<meta property="og:url" content="https://old-host.fr/">'
        "<p>Voir https://old-host.fr dans la prose</p>",
        encoding="utf-8",
    )
    assert sitegen.point_absolute_tags(tmp_path, "https://new.fr") >= 2
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    # The host is swapped and the path kept: `/tech.html` has to stay `/tech.html`.
    assert 'rel="canonical" href="https://new.fr/"' in text
    assert 'property="og:url" content="https://new.fr/"' in text
    assert "Voir https://old-host.fr dans la prose" in text, "prose is not ours to rewrite"


def test_the_deploy_rebuilds_them_after_recording_the_address(tmp_path, monkeypatch):
    """The whole loop: publish, learn the address, make the generated files agree with
    it, publish again. A sitemap that disagrees with where the site lives tells a
    crawler to index somebody else."""
    from corparius import company as cm
    from corparius import deploy
    from corparius.tools import effects as tools

    monkeypatch.setattr(paths, "companies_dir", lambda: tmp_path)
    _company(tmp_path)
    folder = _site(tmp_path / "c", pages=("index.html",))
    (folder / "index.html").write_text(
        '<title>t</title><link rel="canonical" href="https://old.fr/">', encoding="utf-8"
    )
    uploads: list[str] = []
    monkeypatch.setattr(
        deploy,
        "deploy_result",
        lambda d: (
            uploads.append(d)
            or {
                "ok": True,
                "provider": "netlify",
                "result": "netlify:https://c-abc.netlify.app",
                "errors": [],
                "skipped": [],
            }
        ),
    )
    monkeypatch.setattr(
        sitecheck, "verify", lambda *a, **k: {"state": sitecheck.UNVERIFIED, "detail": "x"}
    )

    class Ctx:
        company = cm.load(cm.path_for("c"), "c")
        data_path = str(tmp_path / "data")
        store = None

    res = tools._deploy_site(Ctx())
    assert res.ok and "rebuilt for https://c-abc.netlify.app" in res.output
    assert len(uploads) == 2, "the corrected files have to be uploaded too"
    assert "c-abc.netlify.app" in (folder / "sitemap.xml").read_text(encoding="utf-8")
    assert 'href="https://c-abc.netlify.app/"' in (folder / "index.html").read_text(
        encoding="utf-8"
    )


def test_a_canonical_is_inserted_where_there_is_none(tmp_path):
    """I removed Vigil's six canonical tags because they all named a domain the
    operator does not own — right, by the rule that an absolute tag is omitted rather
    than pointed at a guess. But a function that only *rewrites* would have left those
    pages with no canonical at all once an address existed. Half a job."""
    from corparius import sitegen

    (tmp_path / "index.html").write_text("<html><head><title>t</title></head></html>", "utf-8")
    (tmp_path / "tech.html").write_text("<html><head><title>t</title></head></html>", "utf-8")
    (tmp_path / "blog").mkdir()
    (tmp_path / "blog" / "index.html").write_text("<head><title>b</title></head>", "utf-8")

    assert sitegen.point_absolute_tags(tmp_path, "https://x.fr") == 3
    root = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://x.fr/">' in root
    assert '<link rel="canonical" href="https://x.fr/tech.html">' in (
        tmp_path / "tech.html"
    ).read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://x.fr/blog/">' in (
        tmp_path / "blog" / "index.html"
    ).read_text(encoding="utf-8")


def test_an_existing_canonical_is_not_duplicated(tmp_path):
    from corparius import sitegen

    (tmp_path / "index.html").write_text(
        '<head><link rel="canonical" href="https://old.fr/"></head>', encoding="utf-8"
    )
    sitegen.point_absolute_tags(tmp_path, "https://x.fr")
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert text.count('rel="canonical"') == 1 and "old.fr" not in text


def test_nothing_is_inserted_into_markup_of_unknown_shape(tmp_path):
    """No </head> means a fragment rather than a page, and a tag is not pushed blindly
    into markup whose shape nobody knows."""
    from corparius import sitegen

    (tmp_path / "part.html").write_text("<p>a fragment</p>", encoding="utf-8")
    assert sitegen.point_absolute_tags(tmp_path, "https://x.fr") == 0
    assert (tmp_path / "part.html").read_text(encoding="utf-8") == "<p>a fragment</p>"

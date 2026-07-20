"""Lead research must fall back cleanly and never depend on one source."""

from app import leadsource
from app.leadsource import LocalDatasetSource


def test_local_source_is_always_available():
    assert LocalDatasetSource().available() is True


def test_reads_a_local_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "leads.csv"
    csv_path.write_text(
        "name,company,title,email\nJane,Acme,CTO,jane@example.com\n", encoding="utf-8"
    )
    monkeypatch.setenv("CORP_LEADS_CSV", str(csv_path))
    monkeypatch.setenv("CORP_LEAD_SOURCES", "local")
    leads = leadsource.find_leads("", 5)
    assert len(leads) == 1
    assert leads[0].email == "jane@example.com"
    assert leads[0].source == "local"


def test_query_filters_rows(tmp_path, monkeypatch):
    csv_path = tmp_path / "l.csv"
    csv_path.write_text(
        "name,company,title,email\nA,Acme,CTO,a@x.com\nB,Beta,CEO,b@x.com\n", encoding="utf-8"
    )
    monkeypatch.setenv("CORP_LEADS_CSV", str(csv_path))
    monkeypatch.setenv("CORP_LEAD_SOURCES", "local")
    leads = leadsource.find_leads("beta", 5)
    assert len(leads) == 1 and leads[0].company == "Beta"


def test_falls_back_to_empty_without_config(monkeypatch):
    monkeypatch.delenv("CORP_LEADS_CSV", raising=False)
    monkeypatch.delenv("CORP_LEADS_URL", raising=False)
    monkeypatch.setenv("CORP_LEAD_SOURCES", "browser,local")
    assert leadsource.find_leads("x", 3) == []

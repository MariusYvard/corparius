"""Enrichment fills gaps offline without overwriting real data."""

from corparius.enrich import LocalHeuristicEnricher, enrich
from corparius.leadsource import Lead


def test_local_enricher_is_always_available():
    assert LocalHeuristicEnricher().available() is True


def test_company_is_derived_from_the_email_domain():
    lead = enrich(Lead(email="jane@acme-corp.com"))
    assert lead.company == "Acme Corp"


def test_email_is_guessed_from_name_and_domain(monkeypatch):
    monkeypatch.setenv("CORP_ENRICH_DOMAIN", "acme.com")
    lead = enrich(Lead(name="Jane Doe", company="Acme"))
    assert lead.email == "jane.doe@acme.com"


def test_existing_data_is_not_overwritten(monkeypatch):
    monkeypatch.setenv("CORP_ENRICH_DOMAIN", "acme.com")
    lead = enrich(Lead(name="Jane Doe", company="Acme", email="real@x.com"))
    assert lead.email == "real@x.com"

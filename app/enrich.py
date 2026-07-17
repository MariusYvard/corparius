"""Lead enrichment across interchangeable providers with fallback. The local
heuristic provider is always available and fills obvious gaps offline. Plug an
API provider in the same registry to go further; the chain keeps a local fallback.
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from . import cfg
from .leadsource import Lead


class Enricher(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def enrich(self, lead: Lead) -> Lead:
        ...


class LocalHeuristicEnricher(Enricher):
    """Fill gaps offline: a company from an email domain, a guessed email from a
    name plus a known company domain. Never overwrites data already present."""

    name = "local"

    def available(self) -> bool:
        return True

    def enrich(self, lead: Lead) -> Lead:
        if lead.email and "@" in lead.email and not lead.company:
            host = lead.email.split("@", 1)[1]
            lead.company = host.split(".")[0].replace("-", " ").title()
        if not lead.email and lead.name and lead.company:
            domain = cfg.get("CORP_ENRICH_DOMAIN", "")
            parts = lead.name.lower().split()
            if domain and len(parts) >= 2:
                lead.email = f"{parts[0]}.{parts[-1]}@{domain}"
        return lead


REGISTRY: dict[str, Enricher] = {e.name: e for e in [LocalHeuristicEnricher()]}


def _order() -> list[str]:
    raw = cfg.get("CORP_ENRICHERS", "local")
    return [x.strip() for x in raw.split(",") if x.strip()]


def enrich(lead: Lead) -> Lead:
    for name in _order():
        provider = REGISTRY.get(name)
        if provider is None or not provider.available():
            continue
        try:
            lead = provider.enrich(lead)
        except Exception:   # a provider failure must not drop the lead
            continue
    return lead


def enrich_all(leads: list[Lead]) -> list[Lead]:
    return [enrich(lead) for lead in leads]

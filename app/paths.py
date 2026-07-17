"""Where things live on disk.

`<data_path>/sites/<slug>` was spelled out in nine places across the CLI, the
tools, the console and the MCP server. Nine chances to disagree about where a
company's site is, and the operator finds out by getting a 404 on a site that
was built somewhere else.
"""
from __future__ import annotations
import os
from pathlib import Path


def site_dir(data_path: str, slug: str) -> Path:
    return Path(data_path) / "sites" / (slug or "company")


def site_index(data_path: str, slug: str) -> Path:
    return site_dir(data_path, slug) / "index.html"


def published_dir(site_dir_path: str) -> str:
    """Default target of the local deploy provider: a sibling of the built site."""
    return os.path.join(os.path.dirname(str(site_dir_path).rstrip("/\\")), "published")

"""Validate plugins/registry.json.

Every entry must carry name/repo/ref/sha256, download at its pinned ref, match
its SHA-256, and load against the current plugin API version. Run in CI on any PR
that touches the registry (see .github/workflows/plugins-validate.yml). Exits
non-zero on the first failure, with a GitHub-annotated message.

Set CORP_HOME to a throwaway directory so the download lands in an isolated
plugins folder.
"""
from __future__ import annotations
import os
import sys

# Runnable as `python packaging/validate_registry.py` from the repo root: put the
# repo root on sys.path so `app` imports whatever the working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import cfg, plugins


def main() -> int:
    entries = plugins.registry_entries()
    if not entries:
        print("registry is empty; nothing to validate")
        return 0

    for entry in entries:
        for key in ("name", "repo", "ref", "sha256"):
            if not entry.get(key):
                print(f"::error::registry entry is missing '{key}': {entry}")
                return 1

    for entry in entries:
        name = entry["name"]
        try:
            path = plugins.install_from_registry(name)   # download + sha256 verify
            print(f"downloaded and verified '{name}' -> {path}")
        except plugins.PluginError as exc:
            print(f"::error::{name}: {exc}")
            return 1

    cfg.invalidate()
    loaded = plugins.load()
    missing = [e["name"] for e in entries if e["name"] not in loaded]
    if missing:
        print(f"::error::downloaded but failed to load: {', '.join(missing)}")
        return 1
    print(f"validated {len(entries)} plugin(s): {', '.join(loaded)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

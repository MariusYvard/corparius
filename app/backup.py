"""Zip the store and the company configs.

Extracted from cli.cmd_backup so the console can offer the same button. Worth
saying out loud, because this design created the fact: the store now holds the
API keys saved from the console, so a backup zip carries them in the clear.
`describe()` is the sentence the CLI and the console both show.
"""
from __future__ import annotations
import os
import time
import zipfile
from pathlib import Path

from . import paths

# The writable home: backups land under it and it anchors the archive paths. In
# a source checkout this is the repository root (unchanged); frozen, it is the
# per-OS data directory, so the backup carries the operator's real store and
# companies rather than anything inside the read-only bundle.
ROOT = paths.user_home()

WARNING_EN = ("This archive contains data/corparius.sqlite, which holds the API keys "
              "saved from the console in the clear. Treat the file like a password.")
WARNING_FR = ("Cette archive contient data/corparius.sqlite, qui stocke en clair les clés "
              "API enregistrées depuis la console. Traitez le fichier comme un mot de passe.")


def make_backup(data_path: str, out_dir: str | None = None, stamp: str | None = None) -> Path:
    out = Path(out_dir or ROOT / "backups")
    out.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    path = out / f"corparius-backup-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base in (Path(data_path), ROOT / "companies"):
            if not base.is_dir():
                continue
            for root, _dirs, files in os.walk(base):
                if ".trash" in Path(root).parts:
                    continue          # deleted companies are not worth carrying forward
                for name in files:
                    full = Path(root) / name
                    try:
                        arc = full.relative_to(ROOT)
                    except ValueError:
                        arc = Path(base.name) / full.relative_to(base)
                    zf.write(full, str(arc))
    return path


def describe(path: Path, lang: str = "en") -> str:
    size = path.stat().st_size / 1024
    warn = WARNING_FR if lang == "fr" else WARNING_EN
    return f"{path.name} ({size:.0f} KB). {warn}"

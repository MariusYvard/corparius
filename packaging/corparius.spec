# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone corparius binary.

    pip install pyinstaller
    pyinstaller packaging/corparius.spec --noconfirm

Output (one file, so the download is a single artifact):
    dist/corparius            Linux / macOS binary
    dist/corparius.exe        Windows
    dist/corparius.app        macOS application bundle (also produced on macOS)

The console HTML, the example company and .env.example ship as read-only
resources; app/paths.py routes all writable state (the SQLite store, .env, the
companies the operator creates, backups) to a per-OS folder at runtime. The
heavy optionals (playwright/chromium, boto3, anthropic, the MCP SDK) are
excluded on purpose so the base binary stays small; they remain available on the
source/pip and Docker paths.
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent   # packaging/ -> repository root

datas = [
    (str(ROOT / "app" / "webui.html"), "app"),
    (str(ROOT / "companies" / "example"), "companies/example"),
    (str(ROOT / "plugins" / "registry.json"), "plugins"),
    (str(ROOT / ".env.example"), "."),
]

# app modules are imported lazily in several places (orchestrator, sitegen,
# deploy, backup, update_check...), so pull the whole package in explicitly.
hiddenimports = collect_submodules("app")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "playwright", "boto3", "anthropic", "mcp"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="corparius",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX trips more antivirus heuristics than it saves
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,              # keep the [corparius] log visible; matches the project's transparency
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,          # each CI runner builds for its own arch
    codesign_identity=None,    # unsigned; see docs/install.md for the OS warnings
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="corparius.app",
        icon=None,
        bundle_identifier="com.corparius.console",
        info_plist={
            "CFBundleName": "corparius",
            "CFBundleDisplayName": "corparius",
            "LSBackgroundOnly": False,
            "NSHighResolutionCapable": True,
        },
    )

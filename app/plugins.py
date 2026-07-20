"""Third-party plugins: opt-in, auditable extension of corparius' registries.

corparius has seven extension seams, each a module-level registry consumed lazily
at call time (LLM providers, deploy providers, lead sources, enrichers, tools,
company templates, the agent roster). A plugin is a small piece of code that adds
entries to those registries through the documented `register(api)` hook below; the
loader mutates the existing registries in place, so no core registry is restructured.

Safety, in line with the project's ethos (local-first, auditable, no telemetry):

  * Off by default. Nothing loads unless CORP_PLUGINS_ENABLED is true. The loader
    is never called at `import app`; only the real entry points (the CLI, the
    console, the frozen launcher) call load(), so the test suite and plain imports
    stay plugin-free and deterministic.
  * Curated by default. A plugin is "verified" when its name is in the in-repo
    plugins/registry.json (a reviewed, checksummed allow-list). An unverified
    plugin (installed by hand, or from an arbitrary URL) is refused unless the
    operator sets CORP_PLUGINS_ALLOW_UNVERIFIED, which prints an "unaudited code"
    warning.
  * Isolated. A plugin that raises while loading is logged and skipped; it can
    never take the console or a run down with it.

Discovery has two sources so every distribution works: Python entry points (the
`corparius.plugins` group, for pip-installed plugins on the source/Docker paths)
and a drop-in directory (`<user_home>/plugins/<name>/` with a corparius_plugin.json
manifest, for the frozen binaries that have no pip).
"""
from __future__ import annotations
import importlib
import importlib.metadata
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import cfg, paths

log = logging.getLogger("corparius.plugins")

API_VERSION = 1
MANIFEST_NAME = "corparius_plugin.json"
ENTRY_POINT_GROUP = "corparius.plugins"
DISABLED_MARKER = ".disabled"

# Names of plugins already registered this process; makes load() idempotent.
_loaded: set[str] = set()


class PluginAPI:
    """Handed to each plugin's register(api) hook. Every method adds one entry to
    a core registry in place. Nothing here touches the network or the disk; the
    plugin decides what to register, corparius decides whether to load it."""

    api_version = API_VERSION

    def register_llm_provider(self, name: str, base: str = "", key_env: str = "",
                              **opts) -> None:
        from . import llm
        llm.OPENAI_COMPAT_PROVIDERS[name] = {"base": base, "key_env": key_env, **opts}

    def register_deploy_provider(self, provider) -> None:
        from . import deploy
        deploy.REGISTRY[provider.name] = provider

    def register_lead_source(self, source) -> None:
        from . import leadsource
        leadsource.REGISTRY[source.name] = source

    def register_enricher(self, enricher) -> None:
        from . import enrich
        enrich.REGISTRY[enricher.name] = enricher

    def register_tool(self, tool) -> None:
        # Tools inherit the HITL gate and the safety firewall at dispatch, so a
        # plugin tool marked hitl=True still waits for a human like any other.
        from . import tools
        tools.TOOLS[tool.name] = tool

    def register_template(self, template: dict) -> None:
        from . import company
        company.TEMPLATES.append(template)

    def customize_agent(self, role, **overrides) -> None:
        """Override fields of an existing agent's spec (system_prompt, playbook,
        cadence_hours, difficulty, model). Adding a brand-new role is not
        supported in this API version (AgentRole is a fixed enum)."""
        from . import agents
        from .models import AgentRole
        key = role if isinstance(role, AgentRole) else AgentRole(str(role))
        spec = agents.ROSTER.get(key)
        if spec is None:
            raise ValueError(f"unknown agent role: {role}")
        for field_name, value in overrides.items():
            if not hasattr(spec, field_name):
                raise ValueError(f"unknown AgentSpec field: {field_name}")
            setattr(spec, field_name, value)


@dataclass
class PluginManifest:
    name: str
    version: str = "0.0.0"
    api_version: int = 1
    entrypoint: str = ""            # "module:function"
    kinds: list[str] = field(default_factory=list)
    needs_network: bool = False
    description: str = ""
    source: str = "dropin"         # "dropin" | "entrypoint"
    path: Path | None = None       # the plugin directory, for drop-in plugins
    disabled: bool = False

    @classmethod
    def from_dict(cls, d: dict, path: Path | None = None) -> PluginManifest:
        name = str(d.get("name", "")).strip()
        if not name:
            raise ValueError("plugin manifest missing 'name'")
        entrypoint = str(d.get("entrypoint", "")).strip()
        if ":" not in entrypoint:
            raise ValueError(f"plugin '{name}': entrypoint must be 'module:function'")
        return cls(
            name=name,
            version=str(d.get("version", "0.0.0")),
            api_version=int(d.get("api_version", 1)),
            entrypoint=entrypoint,
            kinds=list(d.get("kinds", [])),
            needs_network=bool(d.get("needs_network", False)),
            description=str(d.get("description", "")),
            source="dropin",
            path=path,
            disabled=bool(path and (path / DISABLED_MARKER).exists()),
        )


def plugins_dir() -> Path:
    """Writable drop-in directory (per-OS home; see app/paths.py)."""
    return paths.user_home() / "plugins"


def registry_entries() -> list[dict]:
    """The curated allow-list shipped in the repo (a read-only resource)."""
    path = paths.resource_dir() / "plugins" / "registry.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("plugins", []))
    except (OSError, ValueError):
        return []


def registry_names() -> set[str]:
    return {str(e.get("name", "")) for e in registry_entries() if e.get("name")}


def _discover_dropin() -> list[PluginManifest]:
    base = plugins_dir()
    out: list[PluginManifest] = []
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        manifest = child / MANIFEST_NAME
        if not manifest.is_file():
            continue
        try:
            out.append(PluginManifest.from_dict(
                json.loads(manifest.read_text(encoding="utf-8")), path=child))
        except (OSError, ValueError) as exc:
            log.warning("skipping plugin in %s: %s", child, exc)
    return out


def _discover_entrypoints() -> list[PluginManifest]:
    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:   # Python < 3.12 selection API
        eps = importlib.metadata.entry_points().get(ENTRY_POINT_GROUP, [])
    out: list[PluginManifest] = []
    for ep in eps:
        out.append(PluginManifest(name=ep.name, entrypoint=ep.value,
                                  api_version=API_VERSION, source="entrypoint"))
    return out


def discover() -> list[PluginManifest]:
    """All installed plugins, drop-in first then entry points, de-duplicated by
    name (a drop-in plugin shadows an entry point of the same name)."""
    seen: dict[str, PluginManifest] = {}
    for m in _discover_dropin() + _discover_entrypoints():
        seen.setdefault(m.name, m)
    return list(seen.values())


def _call_register(manifest: PluginManifest) -> None:
    module_name, _, func_name = manifest.entrypoint.partition(":")
    if manifest.source == "dropin" and manifest.path is not None:
        # Import the plugin's module from its own directory without polluting
        # sys.path permanently.
        p = str(manifest.path)
        added = p not in sys.path
        if added:
            sys.path.insert(0, p)
        try:
            module = importlib.import_module(module_name)
        finally:
            if added:
                try:
                    sys.path.remove(p)
                except ValueError:
                    pass
    else:
        module = importlib.import_module(module_name)
    hook = getattr(module, func_name)
    hook(PluginAPI())


def load() -> list[str]:
    """Discover and register enabled plugins. No-op unless CORP_PLUGINS_ENABLED.
    Returns the names loaded this call. Safe to call more than once."""
    if not cfg.get_bool("CORP_PLUGINS_ENABLED"):
        return []
    allow = cfg.get_csv("CORP_PLUGINS")            # [] means "every installed one"
    allow_unverified = cfg.get_bool("CORP_PLUGINS_ALLOW_UNVERIFIED")
    verified = registry_names()
    just_loaded: list[str] = []
    for manifest in discover():
        if manifest.name in _loaded:
            continue
        if allow and manifest.name not in allow:
            continue
        if manifest.disabled:
            continue
        if manifest.name not in verified and not allow_unverified:
            log.warning("plugin '%s' is not in the verified registry; skipping. "
                        "Set CORP_PLUGINS_ALLOW_UNVERIFIED=true to load it anyway.",
                        manifest.name)
            continue
        if manifest.api_version != API_VERSION:
            log.warning("plugin '%s' targets API v%s, this corparius is v%s; skipping.",
                        manifest.name, manifest.api_version, API_VERSION)
            continue
        try:
            _call_register(manifest)
        except Exception:   # one bad plugin must never break the app
            log.exception("plugin '%s' failed to load; skipping", manifest.name)
            continue
        _loaded.add(manifest.name)
        just_loaded.append(manifest.name)
        log.info("loaded plugin '%s' v%s (%s)", manifest.name, manifest.version,
                 manifest.source)
    return just_loaded


def loaded() -> list[str]:
    return sorted(_loaded)


class PluginError(RuntimeError):
    """A user-facing install/enable error the CLI and console report verbatim."""


# A plugin is source, not a dataset. The largest thing in the curated registry
# is a few hundred kilobytes; this is a ceiling, not a target.
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


def _download(url: str, timeout: float = 30.0) -> bytes:
    """Fetch an archive over https only, up to a fixed ceiling.

    The scheme check is not ceremony: urlopen honours file://, so without it
    `plugin install --url file:///etc/passwd` reads a local file and feeds it to
    the extractor. ftp:// is equally accepted by urlopen and equally unintended.
    The registry only ever produces https URLs, so nothing legitimate is lost.

    The ceiling matters because the read happens before the sha256 check: a
    hostile or wrong URL could otherwise stream until the process dies, and the
    verification that would have rejected it never gets to run.
    """
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
    scheme = urlparse(url).scheme.lower()
    if scheme != "https":
        raise PluginError(f"refusing to download over '{scheme or 'no'}' scheme; "
                          "plugin archives must be https URLs")
    req = Request(url, headers={"User-Agent": "corparius-plugins"})
    with urlopen(req, timeout=timeout) as resp:   # noqa: S310 (https enforced above)
        data = resp.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginError(f"plugin archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB")
    return data


def _safe_extract(data: bytes, dest: Path) -> Path:
    """Extract a .tar.gz into dest/, refusing any member that would escape it
    (tar-slip). Returns the single top-level directory (GitHub archives wrap
    everything in <repo>-<ref>/)."""
    import io
    import tarfile
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        roots = {m.name.split("/", 1)[0] for m in members if m.name}
        for m in members:
            target = (dest / m.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise PluginError(f"unsafe path in archive: {m.name}")
            if m.issym() or m.islnk():
                raise PluginError(f"links are not allowed in a plugin archive: {m.name}")
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            # `filter=` was backported to 3.10.12 and 3.11.4 as a security fix,
            # so on any supported release this branch is unreachable. If it ever
            # is reached, the interpreter is old enough that extracting without
            # the filter is the last thing we should do: refuse instead. Tested
            # by monkeypatching extractall, which exercises it on every version
            # rather than hoping CI runs the right one.
            raise PluginError(
                "this Python is too old to extract a plugin archive safely "
                "(tarfile has no data filter); upgrade to 3.10.12+ or 3.11.4+"
            ) from None
    if len(roots) != 1:
        raise PluginError("archive must contain a single top-level directory")
    return dest / roots.pop()


def _place(extracted_root: Path, name: str) -> Path:
    """Move an extracted plugin into <plugins_dir>/<name>, validating its
    manifest and that the manifest name matches."""
    import shutil
    manifest_path = extracted_root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise PluginError(f"plugin archive has no {MANIFEST_NAME}")
    manifest = PluginManifest.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8")), path=extracted_root)
    if manifest.name != name:
        raise PluginError(f"manifest name '{manifest.name}' does not match '{name}'")
    target = plugins_dir() / name
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(extracted_root), str(target))
    return target


def _archive_url(repo: str, ref: str) -> str:
    return f"{repo.rstrip('/')}/archive/{ref}.tar.gz"


def install_from_registry(name: str) -> Path:
    """Install a VERIFIED plugin from the curated registry: download the pinned
    ref, verify its sha256, then place it. Shared by the CLI and the console."""
    import hashlib
    import tempfile
    entry = next((e for e in registry_entries() if e.get("name") == name), None)
    if entry is None:
        raise PluginError(f"'{name}' is not in the verified registry")
    repo, ref, want = entry.get("repo", ""), entry.get("ref", ""), entry.get("sha256", "")
    if not (repo and ref and want):
        raise PluginError(f"registry entry '{name}' is incomplete (repo/ref/sha256)")
    data = _download(_archive_url(repo, ref))
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise PluginError(f"sha256 mismatch for '{name}': expected {want}, got {got}")
    with tempfile.TemporaryDirectory() as tmp:
        root = _safe_extract(data, Path(tmp))
        return _place(root, name)


def install_from_url(url: str, name: str) -> Path:
    """Install an UNVERIFIED plugin from an arbitrary .tar.gz. Refused unless
    CORP_PLUGINS_ALLOW_UNVERIFIED is set; the caller is responsible for the
    'unaudited code' warning."""
    import tempfile
    if not cfg.get_bool("CORP_PLUGINS_ALLOW_UNVERIFIED"):
        raise PluginError("installing an unverified plugin requires "
                          "CORP_PLUGINS_ALLOW_UNVERIFIED=true")
    data = _download(url)
    with tempfile.TemporaryDirectory() as tmp:
        root = _safe_extract(data, Path(tmp))
        return _place(root, name)


def remove(name: str) -> None:
    import shutil
    target = plugins_dir() / name
    if not target.is_dir():
        raise PluginError(f"plugin '{name}' is not installed")
    shutil.rmtree(target)
    _loaded.discard(name)


def set_enabled(name: str, enabled: bool) -> None:
    """Toggle a drop-in plugin via a .disabled marker file. Takes effect on the
    next load (restart)."""
    target = plugins_dir() / name
    if not target.is_dir():
        raise PluginError(f"plugin '{name}' is not installed")
    marker = target / DISABLED_MARKER
    if enabled:
        marker.unlink(missing_ok=True)
    else:
        marker.write_text("", encoding="utf-8")


def status() -> dict:
    """Snapshot for the CLI and the console: what is installed, verified, enabled
    and loaded, plus the curated registry for install offers."""
    verified = registry_names()
    installed = []
    for m in discover():
        installed.append({
            "name": m.name, "version": m.version, "kinds": m.kinds,
            "source": m.source, "description": m.description,
            "verified": m.name in verified, "disabled": m.disabled,
            "loaded": m.name in _loaded,
        })
    return {
        "enabled": cfg.get_bool("CORP_PLUGINS_ENABLED"),
        "allow_unverified": cfg.get_bool("CORP_PLUGINS_ALLOW_UNVERIFIED"),
        "installed": installed,
        "loaded": loaded(),
        "registry": registry_entries(),
    }

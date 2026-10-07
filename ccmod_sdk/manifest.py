"""Plugin manifest (plugin.json): parsing + validation.

A plugin is a folder:

    plugins/<id>/
        plugin.json      <- this manifest
        main.py          <- entry module (defines a Plugin subclass)
        ...assets (qml, shaders, .ccpack, themes)

plugin.json:
    {
      "id": "hello-button",              # lowercase slug, unique
      "name": "Hello Button",
      "version": "1.0.0",                # semver
      "author": "you",
      "description": "Adds a button to the CCMOD panel.",
      "ccmod": ">=0.1",                  # SDK versions this plugin supports
      "capcut": ["8.9", "9.2"],          # CapCut version prefixes ("*" = any)
      "entry": "main.py",                # file inside the plugin folder
      "provides": ["ui"],                # effect | transition | ui | theme | engine | tool
      "permissions": ["ui"]              # what the plugin may touch (see PERMISSIONS)
    }

Permissions gate the Context API: calling `ctx.engine.*` without "engine" raises PermissionError. They exist so a
user can see what a plugin does before enabling it; the SDK never grants anything the manifest does not declare.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SDK_VERSION = "0.1.0"

PERMISSIONS = {
    "ui": "inject QML (buttons, panels, tabs) and read/write UI properties",
    "engine": "call CapCut controllers, seek the playhead, read engine state",
    "render": "rewrite shaders / hook the render pipeline",
    "draft": "read and modify project drafts (with DraftGuard backups)",
    "effects": "install, list and apply CCMOD effects and packs",
    "network": "redirect CapCut's network requests to local content",
    "files": "read/write files inside the plugin's own data folder",
    "builds": "inspect and launch installed CapCut builds",
    "tools": "expose tools to MCP clients and the CCMOD tool server",
    "media": "import files into CapCut's media pool",
    "process": "run external programs (Blender, ffmpeg, ...) on this PC",
    "apps": "run external apps described by JSON specs and import their results",
}
PROVIDES = {"effect", "transition", "ui", "theme", "engine", "tool"}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class ManifestError(ValueError):
    pass


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _check_constraint(constraint: str, version: str) -> bool:
    """Tiny constraint language: '>=0.1', '>0.1.2', '<=1', '<2', '==0.1.0', or '*'. Comma = AND."""
    v = _vtuple(version)
    for part in (p.strip() for p in constraint.split(",") if p.strip()):
        if part == "*":
            continue
        m = re.match(r"^(>=|<=|==|>|<)?\s*([\d.]+)$", part)
        if not m:
            raise ManifestError(f"bad version constraint {part!r}")
        op, want = m.group(1) or "==", _vtuple(m.group(2))
        n = max(len(v), len(want))
        a, b = v + (0,) * (n - len(v)), want + (0,) * (n - len(want))
        ok = {">=": a >= b, "<=": a <= b, "==": a == b, ">": a > b, "<": a < b}[op]
        if not ok:
            return False
    return True


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    author: str = ""
    description: str = ""
    ccmod: str = "*"
    capcut: list[str] = field(default_factory=lambda: ["*"])
    entry: str = "main.py"
    provides: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    license: str = ""
    homepage: str = ""
    path: Path | None = None            # plugin folder (set by load)

    def compatible_with_sdk(self, sdk_version: str = SDK_VERSION) -> bool:
        return _check_constraint(self.ccmod, sdk_version)

    def compatible_with_capcut(self, build_version: str) -> bool:
        return any(c == "*" or build_version.startswith(c) for c in self.capcut)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("id", "name", "version", "author", "description", "ccmod", "capcut",
                                           "entry", "provides", "permissions", "license", "homepage")}
        return d


def parse(data: dict, path: Path | None = None) -> Manifest:
    """Validate a manifest dict. Raises ManifestError with a precise message."""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    for key in ("id", "name", "version"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ManifestError(f"missing required field {key!r}")
    if not _ID.match(data["id"]):
        raise ManifestError(f"id {data['id']!r} must be a lowercase slug (a-z 0-9 . _ -), 2-63 chars")
    if not _SEMVER.match(data["version"]):
        raise ManifestError(f"version {data['version']!r} must be semver (e.g. 1.0.0)")
    known = {"id", "name", "version", "author", "description", "ccmod", "capcut", "entry", "provides",
             "permissions", "license", "homepage"}
    extra = set(data) - known
    if extra:
        raise ManifestError(f"unknown field(s): {sorted(extra)}")
    perms = data.get("permissions", [])
    if not isinstance(perms, list) or any(p not in PERMISSIONS for p in perms):
        bad = [p for p in perms if p not in PERMISSIONS] if isinstance(perms, list) else perms
        raise ManifestError(f"unknown permission(s) {bad}; allowed: {sorted(PERMISSIONS)}")
    prov = data.get("provides", [])
    if not isinstance(prov, list) or any(p not in PROVIDES for p in prov):
        raise ManifestError(f"'provides' must be a list drawn from {sorted(PROVIDES)}")
    capcut = data.get("capcut", ["*"])
    if not isinstance(capcut, list) or not capcut or not all(isinstance(c, str) for c in capcut):
        raise ManifestError("'capcut' must be a non-empty list of version prefixes")
    entry = data.get("entry", "main.py")
    if not isinstance(entry, str) or entry.startswith(("/", "\\")) or ".." in Path(entry).parts:
        raise ManifestError("'entry' must be a relative path inside the plugin folder")
    m = Manifest(id=data["id"], name=data["name"], version=data["version"], author=data.get("author", ""),
                 description=data.get("description", ""), ccmod=data.get("ccmod", "*"), capcut=list(capcut),
                 entry=entry, provides=list(prov), permissions=list(perms), license=data.get("license", ""),
                 homepage=data.get("homepage", ""), path=path)
    _check_constraint(m.ccmod, SDK_VERSION)      # validates the constraint syntax
    return m


def load(folder: Path) -> Manifest:
    f = Path(folder) / "plugin.json"
    if not f.exists():
        raise ManifestError(f"{folder}: no plugin.json")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"{f}: invalid JSON ({e})") from e
    m = parse(data, Path(folder))
    if not (Path(folder) / m.entry).exists():
        raise ManifestError(f"{f}: entry file {m.entry!r} not found")
    return m

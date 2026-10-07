"""Effect and transition packs: validation, installation, uninstallation.

A pack is a self-contained folder or .ccpack zip that declares what it needs
(how many shader passes, which capabilities) and lets the installer pick a
compatible donor at install time. The author never touches a CapCut directory
path or UUID.

Pack manifest has two roles:
  1. ccmod metadata (id, name, version, kind, description, author, requires)
  2. The `effect` array IS the donor's generalEffect.json content

The donor is bound at install time, passed as a parameter to packs.install.
Never written into the pack. Uninstall and reinstall can bind a different
donor with no change to the file.

Two formats:
  - Folder (schema 2 or 3) - for authoring, drag folder onto the window
  - .ccpack zip (schema 2 or 3) - for distribution, drag zip onto the window
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field

try:
    from ccmod_log import get_logger, sha256_file, file_state
    _log = get_logger("packs")
except ImportError:
    # Fallback if ccmod_log not available
    class _StubLog:
        def debug(self, *a, **kw): pass
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def exception(self, *a, **kw): pass
        def file_write(self, *a, **kw): pass
        def rpdb_op(self, *a, **kw): pass
        def install_transcript(self, *a, **kw): pass
        def uninstall_transcript(self, *a, **kw): pass
    _log = _StubLog()
    def sha256_file(p):
        import hashlib
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    def file_state(p):
        from pathlib import Path
        pp = Path(p)
        if not pp.exists():
            return (0, "missing", 0.0)
        import os as _os
        stat = pp.stat()
        return (stat.st_size, sha256_file(pp), stat.st_mtime)
from datetime import datetime
from enum import Enum
from pathlib import Path

import slots

SCHEMA_VERSION = 3
SPEC_VERSION = 4     # docs/CCPACK-SPEC.md; `spec` replaces `schema` in pack.json
MANIFEST_NAMES = {"pack": "pack.json", "effect": "effect.json", "transition": "transition.json"}
REGISTRY_NAME = "installed.json"
PACK_BACKUP_SUFFIX = ".pack-original.bak"
CCPACK_EXTENSION = ".ccpack"
_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
RPDB_PENDING_NAME = "ccmod-rpdb-pending.json"

_ID_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789.-_")


class PackError(Exception):
    """Raised when a pack is malformed, unsupported, or unsafe to install."""


class CapabilityError(PackError):
    """Raised when a pack needs a CapCut capability not yet confirmed."""


class Kind(Enum):
    EFFECT = "effect"
    TRANSITION = "transition"


@dataclass(frozen=True)
class ShaderPass:
    frag: str
    vert: str | None = None


@dataclass(frozen=True)
class ExtraFile:
    source: str
    destination: str


@dataclass(frozen=True)
class Requirements:
    """What a pack needs from the donor. Used to match packs to donors."""
    frag_passes: int = 1
    vert_passes: int = 0
    progress: bool = False          # needs type 3007 (transition progress)
    dual_textures: bool = False     # needs type 103 (inputImageTexture + inputImageTexture2)
    gles: int = 2                   # GLES version target


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    uniform: str
    minimum: float = 0.0
    maximum: float = 1.0
    default: float = 0.5


@dataclass
class Pack:
    root: Path
    identifier: str
    name: str
    kind: Kind
    version: str
    requirements: Requirements
    passes: list[ShaderPass]
    effect_json: list = field(default_factory=list)  # generalEffect.json "effect" array
    extra_files: list[ExtraFile] = field(default_factory=list)
    requires: dict = field(default_factory=dict)  # legacy capability requirements
    params: list[Param] = field(default_factory=list)
    author: str = ""
    description: str = ""
    lua: str | None = None
    schema: int = SCHEMA_VERSION
    disabled: bool = False


@dataclass(frozen=True)
class Capabilities:
    time_uniform: bool = False
    lua_runtime: bool = False
    effect_registration: bool = False
    multi_pass: bool = True
    gles3: bool = False

    @classmethod
    def load(cls, path: Path) -> Capabilities:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise PackError(f"{path} is not valid JSON: {exc}") from exc
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: bool(v) for k, v in raw.items() if k in known})


# -- Loaders -----------------------------------------------------------------


def load_pack(root: Path) -> Pack:
    """Read and validate a pack from a directory (schema 1, 2, or 3)."""
    if not root.is_dir():
        raise PackError(f"{root} is not a directory")
    manifest_path = _find_manifest(root)
    raw = _read_json(manifest_path)
    # Spec 4 renamed `schema` to `spec` and moved to pack.json. Older packs
    # keep working; the field that is present decides.
    if "spec" in raw:
        spec = raw.get("spec")
        if spec == SPEC_VERSION:
            return _parse_spec4(root, manifest_path, raw)
        raise PackError(
            f"{manifest_path.name} declares spec {spec}; "
            f"this ccmod implements spec {SPEC_VERSION}"
        )
    schema = raw.get("schema", 0)
    if schema == 1:
        return _parse_schema1(root, manifest_path, raw)
    elif schema == 2:
        return _parse_schema2(root, manifest_path, raw)
    elif schema == 3:
        return _parse_schema3(root, manifest_path, raw)
    else:
        raise PackError(
            f"{manifest_path.name} declares schema {schema}, "
            f"this build understands schema 1-3 and spec {SPEC_VERSION}"
        )


def load_ccpack(path: Path) -> Pack:
    """Read and validate a .ccpack zip file.

    The extracted temp directory persists until cleanup_ccpack() is called.
    It is NOT a TemporaryDirectory — mkdtemp dirs survive GC.
    """
    if not path.is_file():
        raise PackError(f"{path} is not a file")
    if path.suffix.lower() != CCPACK_EXTENSION:
        raise PackError(f"{path.name} must have a .ccpack extension")
    _check_zip_bomb(path)
    _check_zip_traversal(path)
    tmp = Path(tempfile.mkdtemp(prefix="ccpack_"))
    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmp)
        pack = load_pack(tmp)
        pack.root = tmp  # keep pointing to extracted dir for file reads
        pack._ccpack_path = path  # store original path for reference (not used for reads)
        return pack
    except (PackError, zipfile.BadZipFile, Exception) as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise PackError(f"{path.name}: {exc}") from exc


def cleanup_ccpack(pack: Pack) -> None:
    """Remove the temp directory created by load_ccpack.

    Call after install is complete (or on error) to avoid leaking temp dirs.
    Safe to call on folder-loaded packs (no-op).
    """
    if hasattr(pack, "_ccpack_path") and pack.root.is_dir():
        if str(pack.root).startswith(tempfile.gettempdir()):
            shutil.rmtree(pack.root, ignore_errors=True)


def discover(*folders: Path) -> list[Pack]:
    """Load every valid pack under the given folders, skipping broken ones."""
    packs: list[Pack] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for child in sorted(folder.iterdir()):
            try:
                if child.is_dir():
                    packs.append(load_pack(child))
                elif child.suffix.lower() == CCPACK_EXTENSION:
                    packs.append(load_ccpack(child))
            except PackError:
                continue
    return packs


# -- Parsers -----------------------------------------------------------------


def _parse_schema1(root: Path, manifest_path: Path, raw: dict) -> Pack:
    _validate_id(raw)
    kind = _validate_kind(raw, manifest_path)
    install = raw.get("install", {})
    if not isinstance(install, dict):
        raise PackError("install must be an object")
    donor = install.get("donor")
    if not donor:
        raise PackError("install.donor is required for schema 1 packs")
    passes = _parse_passes(root, install.get("passes", []), "install.passes")
    lua_rel = raw.get("lua")
    lua_path = str(lua_rel) if lua_rel else None
    return Pack(
        root=root, identifier=str(raw["id"]), name=str(raw["name"]), kind=kind,
        version=str(raw["version"]), slot=Slot(frag_passes=len(passes), donor=donor),
        passes=passes, requires=dict(raw.get("requires", {})),
        params=_parse_params(raw.get("params", [])),
        author=str(raw.get("author", "")), description=str(raw.get("description", "")),
        lua=lua_path, schema=1,
    )


def _parse_schema2(root: Path, manifest_path: Path, raw: dict) -> Pack:
    _validate_id(raw)
    kind = _validate_kind(raw, manifest_path)
    slot_raw = raw.get("slot", {})
    if not isinstance(slot_raw, dict):
        raise PackError("slot must be an object")
    passes = _parse_passes(root, raw.get("passes", []), "passes")
    extra_files = _parse_extra_files(root, raw.get("files", []))
    lua_rel = raw.get("lua")
    lua_path = str(lua_rel) if lua_rel else None
    params = _parse_params(raw.get("params", []))
    _validate_uniforms(root, passes, params)
    fmt = str(raw.get("format", "adjust"))
    # Schema 2 backward compat: extract requirements from slot
    slot_raw2 = raw.get("slot", {}) if isinstance(raw.get("slot"), dict) else {}
    reqs = Requirements(
        frag_passes=int(slot_raw2.get("frag_passes", 1)),
        vert_passes=int(slot_raw2.get("vert_passes", 0)),
        progress=fmt == "generaleffect",
        dual_textures=fmt == "generaleffect",
        gles=int(raw.get("requires", {}).get("gles", 2)),
    )
    # For schema 2 generaleffect packs, extract the effect array from ge_slot
    effect_array = []
    if fmt == "generaleffect":
        effect_array = raw.get("effect", [])  # if it has an explicit effect array
    return Pack(
        root=root, identifier=str(raw["id"]), name=str(raw["name"]), kind=kind,
        version=str(raw["version"]), requirements=reqs, passes=passes,
        extra_files=extra_files, requires=dict(raw.get("requires", {})),
        params=params, author=str(raw.get("author", "")),
        description=str(raw.get("description", "")), lua=lua_path, schema=2,
        effect_json=effect_array,
        disabled=bool(raw.get("disabled", False)),
    )


def _parse_spec4(root: Path, manifest_path: Path, raw: dict) -> Pack:
    """Spec 4: fixed entry names, intent-declaring manifest (docs/CCPACK-SPEC.md).

    The uniform contract is derived from `requires` rather than spelled out, so
    an author cannot mistype inputTextureIndex or declare an unimplemented type.
    """
    _validate_id(raw)
    kind = _validate_kind(raw, manifest_path)

    req_raw = raw.get("requires", {})
    if not isinstance(req_raw, dict):
        raise PackError("requires must be an object")
    clips = int(req_raw.get("clips", 2))
    requirements = Requirements(
        frag_passes=int(req_raw.get("passes", 1)),
        vert_passes=0,
        progress=bool(req_raw.get("progress", True)),
        dual_textures=(clips >= 2),
        gles=2,
    )

    frag = root / "shader" / "main.frag"
    if not frag.is_file():
        raise PackError(
            f"'{raw.get('name', root.name)}' has no shader/main.frag. "
            f"Spec {SPEC_VERSION} uses fixed entry names."
        )
    passes = [ShaderPass(frag="shader/main.frag", vert=(
        "shader/main.vert" if (root / "shader" / "main.vert").is_file() else ""))]

    return Pack(
        root=root, identifier=str(raw["id"]), name=str(raw["name"]), kind=kind,
        version=str(raw.get("version", "1.0.0")), requirements=requirements,
        passes=passes, extra_files=[], requires=dict(req_raw), params=[],
        author=str(raw.get("author", "")),
        description=str(raw.get("description", "")), lua=None, schema=SPEC_VERSION,
        effect_json=[], disabled=bool(raw.get("disabled", False)),
    )


def _parse_schema3(root: Path, manifest_path: Path, raw: dict) -> Pack:
    """Schema 3: no donor, manifest IS the generalEffect.json + ccmod metadata."""
    _validate_id(raw)
    kind = _validate_kind(raw, manifest_path)

    # Requirements declare what the pack needs (not where it goes)
    req_raw = raw.get("requires", {})
    if not isinstance(req_raw, dict):
        raise PackError("requires must be an object")
    requirements = Requirements(
        frag_passes=int(req_raw.get("frag_passes", 1)),
        vert_passes=int(req_raw.get("vert_passes", 0)),
        progress=bool(req_raw.get("progress", False)),
        dual_textures=bool(req_raw.get("dual_textures", False)),
        gles=int(req_raw.get("gles", 2)),
    )

    passes = _parse_passes(root, raw.get("passes", []), "passes")
    extra_files = _parse_extra_files(root, raw.get("files", []))
    lua_rel = raw.get("lua")
    lua_path = str(lua_rel) if lua_rel else None
    params = _parse_params(raw.get("params", []))
    _validate_uniforms(root, passes, params)

    # The effect array is the generalEffect.json content CapCut reads
    effect_array = raw.get("effect", [])
    if not isinstance(effect_array, list):
        raise PackError("effect must be a list (generalEffect.json content)")

    return Pack(
        root=root, identifier=str(raw["id"]), name=str(raw["name"]), kind=kind,
        version=str(raw["version"]), requirements=requirements, passes=passes,
        extra_files=extra_files, requires=dict(raw.get("requires", {})),
        params=params, author=str(raw.get("author", "")),
        description=str(raw.get("description", "")), lua=lua_path, schema=3,
        effect_json=effect_array,
        disabled=bool(raw.get("disabled", False)),
    )


def check_capabilities(pack: Pack, capabilities: Capabilities) -> None:
    if pack.requires.get("time_uniform") and not capabilities.time_uniform:
        raise CapabilityError(
            f"{pack.name} needs a time uniform, which has not been confirmed "
            "for this CapCut build. Installing would produce a static frame."
        )
    if pack.requires.get("lua") and not capabilities.lua_runtime:
        raise CapabilityError(
            f"{pack.name} needs the Amaz Lua runtime, which has not been "
            "surveyed yet."
        )
    if pack.requires.get("gles") == 3 and not capabilities.gles3:
        raise CapabilityError(
            f"{pack.name} targets GLES 3, which is not confirmed."
        )
    if len(pack.passes) > 1 and not capabilities.multi_pass:
        raise CapabilityError(
            f"{pack.name} needs {len(pack.passes)} passes; multi-pass not confirmed."
        )


def validate_shaders(pack: Pack, validator: str = "glslangValidator") -> list[str]:
    warnings: list[str] = []
    for index, shader_pass in enumerate(pack.passes):
        for stage, rel_path in (("frag", shader_pass.frag), ("vert", shader_pass.vert)):
            if rel_path is None:
                continue
            path = pack.root / rel_path
            if not path.exists():
                continue
            try:
                result = subprocess.run(
                    [validator, "-S", stage, str(path)],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except FileNotFoundError:
                warnings.append(
                    f"{validator} not on PATH; shaders not compile-checked. "
                    "Install glslangValidator from "
                    "https://github.com/KhronosGroup/glslang/releases"
                )
                return warnings
            except subprocess.TimeoutExpired:
                raise PackError(
                    f"{rel_path} took >30s to compile; check for unbounded loop"
                ) from None
            if result.returncode != 0:
                detail = (result.stdout or result.stderr).strip()
                raise PackError(
                    f"pass {index} ({rel_path}) failed to compile:\n{detail}"
                )
    return warnings


@dataclass
class DonorInfo:
    """A donor effect the user can install into. Passed to install()."""
    effect_id: str
    md5: str
    title: str
    is_transition: bool = True
    is_duplicate: bool = False
    occupied_by: str = ""  # pack id if occupied
    frag_count: int = 0


def install(
    pack: Pack, capcut_root: Path, capabilities: Capabilities,
    *, donor: DonorInfo | None = None, dry_run: bool = False,
) -> list[Path]:
    """Install a pack into a donor effect.

    For schema 3 (GeneralEffect) packs, donor must be provided.
    For schema 2 packs with an embedded donor path, donor is optional.
    """
    if pack.disabled:
        raise PackError(
            f"'{pack.name}' is disabled: known-broken. Not installable."
        )
    check_capabilities(pack, capabilities)

    # GeneralEffect install with user-selected donor (schema 3 or schema 2 with donor override)
    if pack.kind is Kind.TRANSITION and donor is not None:
        if donor is None:
            raise PackError(
                f"Schema 3 transition pack requires a donor. "
                f"Call install(pack, ..., donor=DonorInfo(...))."
            )
        targets = _install_generaleffect_v3(pack, capcut_root, donor, dry_run=dry_run)
        if dry_run:
            return targets
        # Rename the donor's title in rp.db to the pack's display name
        # This makes the transition appear as the pack name in CapCut's UI
        _rename_donor_title(capcut_root, donor.effect_id, donor.title, pack.name)
        _record_installed_ge(capcut_root, pack, targets, donor.effect_id,
                             donor_title=pack.name, donor_original_title=donor.title)
        return targets

    # Schema 2 backward compat: use embedded donor path if present
    if pack.schema == 2:
        # Check for old-style slot.donor in the raw manifest
        raw = _read_json(_find_manifest(pack.root))
        slot_raw = raw.get("slot", {})
        donor_path = slot_raw.get("donor") if isinstance(slot_raw, dict) else None

        if donor_path:
            donor_dir = (capcut_root / donor_path).resolve()
            if not _is_within(donor_dir, capcut_root.resolve()):
                raise PackError(f"donor path {donor_path!r} escapes install")
            if not donor_dir.is_dir():
                raise PackError(f"donor slot {donor_path} not found")
            registry = _read_registry(capcut_root)
            donor_str = str(donor_dir.relative_to(capcut_root.resolve())).replace("\\", "/")
            for pid, entry in registry.items():
                if entry.get("donor", "").replace("\\", "/") == donor_str and pid != pack.identifier:
                    raise PackError(
                        f"donor {donor_path!r} is already occupied by "
                        f"'{entry.get('name', pid)}' (id={pid}). "
                        f"Uninstall it first."
                    )
        else:
            raise PackError(
                f"Pack '{pack.name}' has no donor specified. "
                f"A donor effect must be selected before installing."
            )

        if pack.kind is Kind.TRANSITION:
            targets = _resolve_transition_targets(donor_dir, pack)
        else:
            targets = _resolve_targets(donor_dir, pack)

        if dry_run:
            _log.info(f"DRY RUN schema2: would write to {[(s, str(t)) for s, t in targets]}")
            return [target for _, target in targets]

        written: list[Path] = []
        backups_made: list[Path] = []
        for source_rel, target in targets:
            source_path = pack.root / source_rel
            size_before, sha_before, mtime_before = file_state(target)
            bp = _backup_once(target)
            if bp and bp.exists():
                backups_made.append(bp)
            # Write content then restore original mtime (integrity check bypass)
            target.write_bytes(source_path.read_bytes())
            if mtime_before > 0:
                os.utime(target, (mtime_before, mtime_before))
            size_after, sha_after, mtime_after = file_state(target)
            _log.file_write(str(target), size_before, sha_before, mtime_before,
                            size_after, sha_after, mtime_after)
            written.append(target)
        for extra in pack.extra_files:
            source_path = pack.root / extra.source
            target_path = donor_dir / extra.destination
            size_before, sha_before, mtime_before = file_state(target_path)
            bp = _backup_once(target_path)
            if bp and bp.exists():
                backups_made.append(bp)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(source_path.read_bytes())
            if mtime_before > 0:
                os.utime(target_path, (mtime_before, mtime_before))
            size_after, sha_after, mtime_after = file_state(target_path)
            _log.file_write(str(target_path), size_before, sha_before, mtime_before,
                            size_after, sha_after, mtime_after)
            written.append(target_path)
        _record_installed(capcut_root, pack, written, str(donor_dir))
        _log.install_transcript(pack.identifier, str(donor_dir), written, backups_made, "SUCCESS")
        return written

    raise PackError(f"Cannot install pack with schema {pack.schema} and kind {pack.kind}")


def uninstall(pack_id: str, capcut_root: Path) -> list[Path]:
    # Check GeneralEffect registry first (User Data/installed.json)
    ge_reg_path = _ge_registry_path(capcut_root)
    if ge_reg_path.exists():
        ge_registry = _read_ge_registry(capcut_root)
        if pack_id in ge_registry:
            return _uninstall_generaleffect(pack_id, capcut_root)

    registry = _read_registry(capcut_root)
    entry = registry.get(pack_id)
    if entry is None:
        raise PackError(f"No installed pack with that ID. It may have already been uninstalled.")

    restored: list[Path] = []
    for raw_path in entry.get("files", []):
        target = Path(raw_path)
        backup = target.with_name(target.name + PACK_BACKUP_SUFFIX)
        if not backup.exists():
            raise PackError(
                f"backup for {target.name} is missing. Reinstall CapCut."
            )
        shutil.copy2(backup, target)
        backup.unlink()
        restored.append(target)
    del registry[pack_id]
    _write_registry(capcut_root, registry)
    return restored


# -- Zip safety --------------------------------------------------------------


def _check_zip_bomb(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as zf:
        total_uncompressed = 0
        for info in zf.infolist():
            total_uncompressed += info.file_size
            if info.compress_size > 0 and info.file_size > 0:
                ratio = info.file_size // info.compress_size
                if ratio > _MAX_COMPRESSION_RATIO:
                    raise PackError(
                        f"{path.name}: entry {info.filename} has ratio {ratio}:1"
                    )
            if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                raise PackError(f"{path.name}: exceeds 50 MB uncompressed")


def _check_zip_traversal(path: Path) -> None:
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or ":" in name:
                raise PackError(f"{path.name}: absolute path {name!r}")
            normalized = os.path.normpath(name)
            if normalized.startswith("..") or "/.." in normalized or "\\.." in normalized:
                raise PackError(f"{path.name}: traversal {name!r}")
            if info.external_attr >> 16 == 0o120000:
                raise PackError(f"{path.name}: symlink {name!r}")


# -- Helpers -----------------------------------------------------------------


def _find_manifest(root: Path) -> Path:
    found = [root / n for n in MANIFEST_NAMES.values() if (root / n).is_file()]
    if not found:
        raise PackError(
            f"{root.name} has no manifest; expected {list(MANIFEST_NAMES.values())}"
        )
    if len(found) > 1:
        raise PackError(f"{root.name} has both effect.json and transition.json")
    return found[0]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{path.name} is not valid JSON: {exc}") from exc


def _validate_id(raw: dict) -> None:
    i = str(raw["id"])
    if not i or set(i) - _ID_ALLOWED:
        raise PackError(
            f"id {i!r}: only lowercase letters, digits, dot, dash, underscore"
        )


def _validate_kind(raw: dict, manifest_path: Path) -> Kind:
    try:
        kind = Kind(raw["kind"])
    except ValueError as exc:
        raise PackError(f"kind must be {[k.value for k in Kind]}") from exc
    # Spec 4 uses one pack.json for every kind; the legacy layout keyed the
    # manifest filename to the kind.
    if manifest_path.name not in ("pack.json", MANIFEST_NAMES[kind.value]):
        raise PackError(
            f"kind {kind.value!r} needs {MANIFEST_NAMES[kind.value]}"
        )
    return kind


def _validate_uniforms(root: Path, passes: list[ShaderPass], params: list[Param]) -> None:
    if not params:
        return
    frag_source = ""
    for sp in passes:
        p = root / sp.frag
        if p.exists():
            frag_source = p.read_text("utf-8")
            break
    if not frag_source:
        return
    # Strip comments so we don't match declarations inside block/line comments
    source_no_comments = _strip_glsl_comments(frag_source)
    for param in params:
        # Match: uniform [precision]? <type> <name1>[, <name2>, ...] ;
        # Precision: lowp | mediump | highp
        # Type: any identifier (float, int, sampler2D, vec2, vec3, vec4, mat3, ...)
        # Comma list: each name may have optional array suffix [N]
        name_escaped = re.escape(param.uniform)
        pattern = (
            r"uniform\s+(?:lowp\s+|mediump\s+|highp\s+)?\w+\s+"
            r"(?:" + name_escaped + r"(?:\s*\[\s*\d+\s*\])?\s*,?\s*)*"
            r"(?:;\s*)?$"
        )
        # Simpler: search for the name as a standalone token after the type
        # Match: uniform [precision] <type> <anything>; then check name appears
        # as a word in the comma-separated names
        decl_pattern = (
            r"uniform\s+(?:lowp\s+|mediump\s+|highp\s+)?\w+\s+"
            r"(?:[a-zA-Z_]\w*(?:\s*\[\s*\d+\s*\])?\s*,\s*)*"
            + name_escaped +
            r"(?:\s*\[\s*\d+\s*\])?"
            r"(?:\s*,\s*[a-zA-Z_]\w*(?:\s*\[\s*\d+\s*\])?\s*)*\s*;"
        )
        if not re.search(decl_pattern, source_no_comments):
            raise PackError(
                f"param {param.key!r} declares uniform {param.uniform!r} "
                f"but no matching uniform declaration was found in the shader source"
            )


def _strip_glsl_comments(source: str) -> str:
    """Remove GLSL line comments (//) and block comments (/* */)."""
    # Block comments first (non-greedy)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    # Line comments
    source = re.sub(r"//[^\n]*", "", source)
    return source


def _parse_passes(root: Path, raw: object, label: str) -> list[ShaderPass]:
    if not isinstance(raw, list) or not raw:
        raise PackError(f"{label} must be a non-empty list")
    passes: list[ShaderPass] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict) or "frag" not in entry:
            raise PackError(f"{label}[{idx}] needs a 'frag' key")
        frag_rel = str(entry["frag"])
        _validate_path_in_root(root, frag_rel, f"{label}[{idx}].frag")
        vert_rel = entry.get("vert")
        if vert_rel is not None:
            vert_rel = str(vert_rel)
            _validate_path_in_root(root, vert_rel, f"{label}[{idx}].vert")
        passes.append(ShaderPass(frag=frag_rel, vert=vert_rel))
    return passes


def _parse_extra_files(root: Path, raw: object) -> list[ExtraFile]:
    if not isinstance(raw, list):
        return []
    files: list[ExtraFile] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PackError(f"files[{idx}] must be an object")
        if "source" not in entry or "destination" not in entry:
            raise PackError(f"files[{idx}] needs 'source' and 'destination'")
        source = str(entry["source"])
        dest = str(entry["destination"])
        _validate_path_in_root(root, source, f"files[{idx}].source")
        if dest.startswith("/") or dest.startswith("\\") or ":" in dest:
            raise PackError(f"files[{idx}].destination {dest!r}: must be relative")
        normalized = os.path.normpath(dest)
        if normalized.startswith("..") or "/.." in normalized or "\\.." in normalized:
            raise PackError(f"files[{idx}].destination {dest!r}: traversal")
        files.append(ExtraFile(source=source, destination=dest))
    return files


def _parse_params(raw: object) -> list[Param]:
    if not isinstance(raw, list):
        raise PackError("params must be a list")
    params: list[Param] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PackError(f"params[{idx}] must be an object")
        for required in ("key", "label", "uniform"):
            if required not in entry:
                raise PackError(f"params[{idx}] missing {required!r}")
        mini = float(entry.get("min", 0.0))
        maxi = float(entry.get("max", 1.0))
        if mini >= maxi:
            raise PackError(f"params[{idx}]: min >= max")
        default = float(entry.get("default", mini))
        if not mini <= default <= maxi:
            raise PackError(f"params[{idx}]: default outside range")
        params.append(Param(key=str(entry["key"]), label=str(entry["label"]),
                            uniform=str(entry["uniform"]),
                            minimum=mini, maximum=maxi, default=default))
    return params


def _install_generaleffect_v3(
    pack: Pack, capcut_root: Path, donor: 'DonorInfo', *, dry_run: bool = False,
) -> list[Path]:
    """Install a schema 3 GeneralEffect transition into a user-selected donor."""
    import os

    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
    cache_effect = user_data / "Cache" / "effect"
    effect_dir = cache_effect / donor.effect_id
    extracted = effect_dir / donor.md5

    if not extracted.is_dir():
        raise PackError(
            f"That transition is no longer in your CapCut cache. "
            f"Pick a different one from the list."
        )

    frag_files = sorted(extracted.rglob("*.frag"))
    if not frag_files:
        raise PackError(f"That transition's shader files are missing. Try a different one.")

    # Prefer GLES frags (that's what CapCut renders on Windows)
    gles_frags = [f for f in frag_files if "shaderGLES" in str(f) or ("shader" in str(f) and "Metal" not in str(f))]
    if not gles_frags:
        gles_frags = frag_files  # fallback: use all frags

    # Target: only the first GLES frag. Multi-frag donors have sub-effects
    # with different uniform sets - overwriting all of them breaks the pipeline.
    # The first frag in a GESticker layout is the main transition shader.
    targets: list[Path] = [gles_frags[0]] if gles_frags else [frag_files[0]]

    if dry_run:
        _log.info(f"DRY RUN: would write to {targets}")
        return targets

    written: list[Path] = []
    backups_made: list[Path] = []
    errors: list[str] = []
    source_map: dict = {}  # target_path -> source_path, for zip patching
    for i, target in enumerate(targets):
        pass_idx = min(i, len(pack.passes) - 1)
        source = pack.root / pack.passes[pass_idx].frag
        shader_bytes = source.read_bytes()
        source_map[target] = source

        # Capture state before write
        size_before, sha_before, mtime_before = file_state(target)
        _log.info(f"Before write: {target} size={size_before} sha={sha_before[:16]} mtime={mtime_before}")

        # Backup (must succeed before we write)
        try:
            backup_path = _backup_once(target)
            if backup_path and backup_path.exists():
                backups_made.append(backup_path)
            else:
                raise PackError(f"Could not create backup for {target.name}")
        except PackError:
            raise
        except Exception as e:
            raise PackError(f"Backup failed for {target.name}: {e}. Install aborted.")

        # Write
        target.write_bytes(shader_bytes)
        if mtime_before > 0:
            os.utime(target, (mtime_before, mtime_before))

        # Capture state after write
        size_after, sha_after, mtime_after = file_state(target)
        _log.file_write(str(target), size_before, sha_before, mtime_before,
                        size_after, sha_after, mtime_after)

        # Post-write verification
        if sha_after != sha256_file(source):
            msg = f"Post-write verification FAILED: {target} sha mismatch (expected {sha256_file(source)[:16]})"
            _log.error(msg)
            errors.append(msg)
        if abs(mtime_after - mtime_before) > 0.001:
            msg = f"mtime not preserved: {target} before={mtime_before} after={mtime_after}"
            _log.warning(msg)
            errors.append(msg)

        written.append(target)

    if errors:
        _log.error(f"Install completed with {len(errors)} errors")
    else:
        _log.info(f"Install verification passed: {len(written)} files OK")

    # Patch the _tmp zip so the shader survives re-extraction on launch.
    # The _tmp file is the source of truth — CapCut extracts from it and
    # overwrites the extracted files. Without patching it, installs silently
    # revert on next launch.
    zip_path = effect_dir / (donor.md5 + "_tmp")
    if zip_path.exists():
        try:
            _patch_zip_shader(zip_path, written, source_map)
            _log.info(f"Patched zip: {zip_path}")
        except Exception as e:
            _log.error(f"Failed to patch zip {zip_path}: {e}")
            errors.append(f"zip patch failed: {e}")
    else:
        _log.warning(f"_tmp zip not found at {zip_path} — extracted-only patch may not survive restart")

    # Update rp.db with the new zip md5.
    # _update_rp_db writes immediately if CapCut is closed, or queues if running.
    # At flush time, the zip's actual md5 is recomputed from disk (not this value).
    try:
        new_zip_md5 = hashlib.md5(zip_path.read_bytes()).hexdigest() if zip_path.exists() else donor.md5
        if new_zip_md5 != donor.md5:
            # EVERY rp.db, not just the first. There are two ressdk_db dirs on
            # this install, and a `break` here left the second one holding the
            # pre-install md5. CapCut reads the stale row, decides the package
            # on disk does not match the catalogue, re-downloads it, and the
            # install silently reverts. Observed live on donor
            # 6726711499676455435: 2 rows patched, 3 rows stale, package
            # re-downloaded, both the zip and the extracted frag back to stock.
            for db_path in _all_rpdb_paths(user_data):
                _update_rp_db(db_path, donor.effect_id, new_zip_md5)
    except Exception as e:
        # Not cosmetic: if rp.db keeps the old md5, CapCut sees a mismatch
        # against the patched zip, re-downloads the package and reverts the
        # install. This is the exact hole df34eda was opened to close, so it
        # counts as an install error rather than a warning.
        _log.exception("rp.db md5 update failed")
        errors.append(f"catalog md5 update failed: {e}")

    _log.install_transcript(pack.identifier, donor.title, written, backups_made,
                            "SUCCESS" if not errors else "PARTIAL",
                            error="; ".join(errors) if errors else None)

    return written


def _patch_zip_shader(zip_path: Path, written_files: list[Path],
                      source_map: dict) -> None:
    """Patch shader files inside the _tmp zip to match what was written to disk.

    written_files: list of extracted file paths that were patched
    source_map: dict mapping extracted path -> source pack file (for reading new content)
    """
    import tempfile

    # Read all entries from the original zip
    with zipfile.ZipFile(zip_path, 'r') as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}

    # Map extracted paths to zip entry names
    # The extracted dir is <effect_dir>/<md5>/<rest...>
    # The zip entries are <rest...> (relative to the extracted root)
    extracted_root = zip_path.parent / zip_path.stem.replace("_tmp", "")
    for written_file in written_files:
        try:
            rel = written_file.relative_to(extracted_root)
            zip_entry = str(rel).replace("\\", "/")
        except ValueError:
            continue
        if zip_entry in entries:
            new_bytes = written_file.read_bytes()
            entries[zip_entry] = new_bytes
            _log.info(f"Replaced zip entry '{zip_entry}' ({len(new_bytes)} bytes)")

    # Rewrite the zip
    tmp_zip = zip_path.with_suffix(".tmp_patch")
    with zipfile.ZipFile(tmp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    tmp_zip.replace(zip_path)


def _uninstall_generaleffect(pack_id: str, capcut_root: Path) -> list[Path]:
    """Restore a GeneralEffect transition from backup."""
    import os

    registry = _read_ge_registry(capcut_root)
    entry = registry.get(pack_id)
    if entry is None:
        raise PackError(f"No installed pack with that ID. It may have already been uninstalled.")

    # Every step below undoes part of the install. A step that fails silently
    # leaves the donor patched while the registry says it is clean, which is
    # unrecoverable state -- so failures are collected and raised, never logged
    # and stepped over.
    failures: list[str] = []
    restored: list[Path] = []
    for raw_path in entry.get("files", []):
        target = Path(raw_path)
        backup = target.with_name(target.name + PACK_BACKUP_SUFFIX)
        if backup.exists():
            try:
                size_before, sha_before, mtime_before = file_state(target)
                _log.info(f"Restoring {target} from backup")
                shutil.copy2(backup, target)
                backup.unlink()
                size_after, sha_after, mtime_after = file_state(target)
                _log.file_write(str(target), size_before, sha_before, mtime_before,
                                size_after, sha_after, mtime_after)
                restored.append(target)
            except OSError as e:
                _log.exception(f"Restore failed for {target}")
                failures.append(f"could not restore {target.name}: {e}")
        else:
            _log.error(f"No backup for {target}, cannot restore")
            failures.append(
                f"the backup for {target.name} is missing, so the donor still "
                f"has the custom shader and cannot be put back"
            )

    # Restore the zip to original (patch the restored frag back into the _tmp zip)
    if restored:
        donor_eid = entry.get("donor", "")
        donor_md5 = ""
        # Extract md5 from the first file path: .../effect/<eid>/<md5>/...
        for raw_path in entry.get("files", []):
            parts = Path(raw_path).parts
            for idx, part in enumerate(parts):
                if part == "effect" and idx + 2 < len(parts):
                    donor_md5 = parts[idx + 2]
                    break
            if donor_md5:
                break
        if donor_eid and donor_md5:
            user_data = capcut_root.parent / "User Data"
            if not user_data.is_dir():
                user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
            zip_path = user_data / "Cache" / "effect" / donor_eid / (donor_md5 + "_tmp")
            if zip_path.exists():
                try:
                    # source_map is not available here; _patch_zip_shader reads from disk
                    _patch_zip_shader(zip_path, restored, {})
                    _log.info(f"Restored zip entries: {zip_path}")
                    # Recompute md5 and queue rp.db update with the ORIGINAL md5
                    new_zip_md5 = hashlib.md5(zip_path.read_bytes()).hexdigest()
                    # Every rp.db, same reason as the install path: a partial
                    # update leaves a stale row and CapCut re-downloads.
                    for db_path in _all_rpdb_paths(user_data):
                        _update_rp_db(db_path, donor_eid, donor_md5)
                except Exception as e:
                    _log.exception("Failed to restore zip during uninstall")
                    failures.append(
                        f"the donor's zip could not be put back ({e}); CapCut "
                        f"will re-extract the custom shader on next launch"
                    )

    # Restore the donor's original title in rp.db
    donor_eid = entry.get("donor", "")
    original_title = entry.get("donor_original_title", entry.get("donor_title", ""))
    if donor_eid and original_title:
        try:
            _restore_donor_title(capcut_root, donor_eid, original_title)
        except Exception as e:
            _log.exception("Failed to restore donor title during uninstall")
            failures.append(f"the donor's original name could not be restored ({e})")

    if failures:
        # Drop the files already put back so a retry only attempts what is
        # left, then keep the entry -- deleting it would lose the donor
        # binding and with it any chance of finishing the job.
        restored_str = {str(p) for p in restored}
        entry["files"] = [f for f in entry.get("files", []) if f not in restored_str]
        registry[pack_id] = entry
        _write_ge_registry(capcut_root, registry)
        _log.uninstall_transcript(pack_id, restored, "FAILED", error="; ".join(failures))
        raise PackError(
            "Uninstall could not fully undo the install:\n  - "
            + "\n  - ".join(failures)
            + "\nThe pack is still listed as installed so you can retry after "
              "fixing the cause. Do not delete it from installed.json by hand."
        )

    del registry[pack_id]
    _write_ge_registry(capcut_root, registry)
    _log.uninstall_transcript(pack_id, restored, "SUCCESS")
    return restored


def _resolve_targets(donor_dir: Path, pack: Pack) -> list[tuple[str, Path]]:
    donor_frags = sorted(donor_dir.glob("*.frag"))
    donor_verts = sorted(donor_dir.glob("*.vert"))
    if not donor_frags:
        raise PackError(f"donor slot {donor_dir.name} has no .frag files")
    if len(pack.passes) > len(donor_frags):
        raise PackError(
            f"pack needs {len(pack.passes)} passes, donor has {len(donor_frags)}"
        )
    targets: list[tuple[str, Path]] = []
    for idx, sp in enumerate(pack.passes):
        targets.append((sp.frag, donor_frags[idx]))
        if sp.vert is not None:
            if idx >= len(donor_verts):
                raise PackError(f"pass {idx} needs .vert, donor has none")
            targets.append((sp.vert, donor_verts[idx]))
    return targets


def _resolve_transition_targets(donor_dir: Path, pack: Pack) -> list[tuple[str, Path]]:
    """Map pack shaders onto a MixMode slot's Library/ shader files.

    For transitions, the donor is a MixMode directory.  The frag file lives
    in Library/ShaderData/<library_hash>/shaderGLES/<frag_hash>.frag.

    We replace that frag with the pack's frag, keeping the same filename
    because the xshader binary references it by path.
    """
    if pack.kind is not Kind.TRANSITION:
        return _resolve_targets(donor_dir, pack)

    frags = slots._find_library_frag(donor_dir)
    if not frags:
        raise PackError(
            f"Transition slot {donor_dir.name} has no Library/ frag files"
        )
    if len(pack.passes) > len(frags):
        raise PackError(
            f"Pack needs {len(pack.passes)} passes, slot has {len(frags)} Library frags"
        )

    targets: list[tuple[str, Path]] = []
    for idx, sp in enumerate(pack.passes):
        targets.append((sp.frag, frags[idx]))
        if sp.vert is not None:
            raise PackError("Transition packs with vertex shaders are not supported yet")
    return targets


def _backup_once(target: Path) -> Path:
    backup = target.with_name(target.name + PACK_BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(target, backup)
    return backup


def _registry_path(capcut_root: Path) -> Path:
    return capcut_root / REGISTRY_NAME


def _read_registry(capcut_root: Path) -> dict:
    p = _registry_path(capcut_root)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{p} is corrupt: {exc}") from exc
    if not isinstance(d, dict):
        raise PackError(f"{p} should contain an object")
    return d


def _write_registry(capcut_root: Path, registry: dict) -> None:
    p = _registry_path(capcut_root)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(registry, indent=2), "utf-8")
    t.replace(p)


def _record_installed(capcut_root: Path, pack: Pack, written: list[Path], donor: str = "") -> None:
    registry = _read_registry(capcut_root)
    registry[pack.identifier] = {
        "name": pack.name, "version": pack.version, "kind": pack.kind.value,
        "schema": pack.schema, "donor": donor,
        "files": [str(p) for p in written],
    }
    _write_registry(capcut_root, registry)


def _ge_registry_path(capcut_root: Path) -> Path:
    """GeneralEffect packs record their registry in User Data, not the install dir."""
    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
    return user_data / REGISTRY_NAME


def _read_ge_registry(capcut_root: Path) -> dict:
    p = _ge_registry_path(capcut_root)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise PackError(f"{p} is corrupt: {exc}") from exc
    if not isinstance(d, dict):
        raise PackError(f"{p} should contain an object")
    return d


def _write_ge_registry(capcut_root: Path, registry: dict) -> None:
    p = _ge_registry_path(capcut_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(registry, indent=2), "utf-8")
    t.replace(p)


def _record_installed_ge(capcut_root: Path, pack: Pack, written: list[Path],
                         donor_effect_id: str = "", donor_title: str = "",
                         donor_original_title: str = "") -> None:
    registry = _read_ge_registry(capcut_root)
    registry[pack.identifier] = {
        "name": pack.name, "version": pack.version, "kind": pack.kind.value,
        "schema": pack.schema,
        "donor": donor_effect_id,
        "donor_title": donor_title,  # current display title (may be renamed)
        "donor_original_title": donor_original_title or donor_title,  # restored on uninstall
        "files": [str(p) for p in written],
    }
    _write_ge_registry(capcut_root, registry)


def _validate_path_in_root(root: Path, relative: object, label: str) -> Path:
    p = (root / str(relative)).resolve()
    if not _is_within(p, root.resolve()):
        raise PackError(f"{label} points outside the pack folder")
    return p


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _is_capcut_running() -> bool:
    """Check whether CapCut.exe is currently running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        running = "CapCut.exe" in result.stdout
        _log.debug(f"_is_capcut_running: {running}")
        return running
    except subprocess.TimeoutExpired:
        _log.warning("tasklist timed out, assuming CapCut is running (safe default)")
        return True
    except Exception as e:
        _log.warning(f"tasklist failed ({e}), assuming CapCut is running (safe default)")
        return True


def _all_rpdb_paths(user_data: Path) -> list[Path]:
    """Every rp.db under User Data/Cache/ressdk_db/.

    There is more than one on a real install. Updating only the first leaves a
    stale row; CapCut reads it, decides the cached package does not match the
    catalogue, re-downloads, and the install silently reverts.
    """
    ressdk = user_data / "Cache" / "ressdk_db"
    if not ressdk.is_dir():
        return []
    return [d / "rp.db" for d in sorted(ressdk.iterdir()) if (d / "rp.db").is_file()]


def _find_rpdb_path(user_data: Path) -> Path | None:
    """First rp.db only. Prefer _all_rpdb_paths() for writes."""
    paths = _all_rpdb_paths(user_data)
    return paths[0] if paths else None


def _rename_donor_title(capcut_root: Path, effect_id: str,
                        original_title: str, new_title: str) -> None:
    """Rename a donor's title in rp.db to the pack's display name.

    Uses the same queue-and-flush discipline as md5 updates.
    """
    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
    paths = _all_rpdb_paths(user_data)
    if not paths:
        _log.warning(f"rp.db not found, skipping title rename for {effect_id}")
        return
    for db_path in paths:
        _update_rp_db_title(db_path, effect_id, new_title)


def _restore_donor_title(capcut_root: Path, effect_id: str, original_title: str) -> None:
    """Restore a donor's original title in rp.db on uninstall."""
    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
    paths = _all_rpdb_paths(user_data)
    if not paths:
        _log.warning(f"rp.db not found, skipping title restore for {effect_id}")
        return
    for db_path in paths:
        _update_rp_db_title(db_path, effect_id, original_title)


def _update_rp_db(db_path: Path, effect_id: str, new_md5: str) -> None:
    """Update the md5 field for an effect in rp.db http_cache.

    File writes (shaders) are safe while CapCut runs — the mtime bypass covers them.
    rp.db writes are NEVER safe while CapCut runs — the DB is locked and there is
    no factory copy. If CapCut is running, the update is queued to
    ccmod-rpdb-pending.json and applied on next launch via flush_pending_rpdb_updates().
    """
    running = _is_capcut_running()
    _log.rpdb_op(f"UPDATE md5 for {effect_id}", 0, "", new_md5, not running)
    if running:
        _queue_rpdb_update(db_path, effect_id, action="md5", new_md5=new_md5)
        _log.warning(
            f"rp.db md5 update for {effect_id} queued — CapCut is running. "
            f"Run 'ccmod doctor' or relaunch after closing CapCut to apply."
        )
        return

    _apply_rpdb_update(db_path, effect_id, new_md5)


def _update_rp_db_title(db_path: Path, effect_id: str, new_title: str) -> None:
    """Update the title field for an effect in rp.db http_cache.

    Same queue-and-flush discipline as md5 updates. At flush time, the
    title is written directly (no recompute needed — titles don't change
    on re-download the way md5s do).
    """
    running = _is_capcut_running()
    _log.rpdb_op(f"UPDATE title for {effect_id}", 0, "", new_title, not running)
    if running:
        _queue_rpdb_update(db_path, effect_id, action="title", new_title=new_title)
        _log.warning(
            f"rp.db title update for {effect_id} queued — CapCut is running. "
            f"Run 'ccmod doctor' or relaunch after closing CapCut to apply."
        )
        return

    _apply_rpdb_title_update(db_path, effect_id, new_title)


def _queue_rpdb_update(db_path: Path, effect_id: str, *,
                       action: str = "md5",
                       new_md5: str = "",
                       new_title: str = "") -> None:
    """Queue an rp.db update for later application.

    For md5 updates: new_md5 is recorded for reference only. At flush time,
    the zip's actual md5 is recomputed from disk.
    For title updates: new_title is written directly at flush time.
    """
    pending_path = db_path.parent.parent.parent.parent / RPDB_PENDING_NAME
    # db_path = User Data/Cache/ressdk_db/<hash>/rp.db
    # .parent = <hash>/
    # .parent.parent = ressdk_db/
    # .parent.parent.parent = Cache/
    # .parent.parent.parent.parent = User Data/
    pending = []
    if pending_path.exists():
        try:
            pending = json.loads(pending_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pending = []
    # Replace any existing entry for the same effect_id AND action
    pending = [e for e in pending
               if not (e.get("effect_id") == str(effect_id) and e.get("action") == action)]
    entry: dict = {
        "db_path": str(db_path),
        "effect_id": str(effect_id),
        "action": action,
        "queued_at": datetime.now().isoformat(),
    }
    if action == "md5":
        entry["new_md5"] = new_md5  # remembered value — not trusted at flush time
    elif action == "title":
        entry["new_title"] = new_title
    pending.append(entry)
    pending_path.write_text(json.dumps(pending, indent=2), "utf-8")
    _log.info(f"Queued rp.db update for {effect_id} to {pending_path}")


def _recompute_zip_md5(user_data: Path, effect_id: str) -> str | None:
    """Compute the actual MD5 of the _tmp zip on disk for this effect_id.

    Returns None if the zip doesn't exist.
    """
    effect_dir = user_data / "Cache" / "effect" / str(effect_id)
    if not effect_dir.is_dir():
        return None
    # The _tmp file is named <dir_name>_tmp
    for child in effect_dir.iterdir():
        if child.name.endswith("_tmp") and child.is_file():
            md5 = hashlib.md5(child.read_bytes()).hexdigest()
            _log.info(f"Recomputed zip md5 for {effect_id}: {md5} (file={child.name})")
            return md5
    return None


def flush_pending_rpdb_updates(capcut_root: Path) -> int:
    """Apply any queued rp.db updates. Call this when CapCut is NOT running.

    At flush time, recomputes the zip's actual md5 from disk rather than
    using the remembered value. If CapCut reverted the zip (re-downloaded
    the original), we write the original md5 and rp.db stays consistent.
    If the patched zip is still on disk, we write the patched md5.

    Returns the number of updates applied.
    """
    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"
    pending_path = user_data / RPDB_PENDING_NAME
    if not pending_path.exists():
        return 0

    running = _is_capcut_running()
    if running:
        _log.warning("Cannot flush pending rp.db updates — CapCut is still running.")
        return 0

    try:
        pending = json.loads(pending_path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        _log.error("Pending rp.db queue is corrupt, discarding")
        pending_path.unlink(missing_ok=True)
        return 0

    applied = 0
    for entry in pending:
        db_path = Path(entry["db_path"])
        effect_id = entry["effect_id"]
        action = entry.get("action", "md5")
        if action == "title":
            new_title = entry.get("new_title", "")
            try:
                _apply_rpdb_title_update(db_path, effect_id, new_title)
                applied += 1
            except PackError as e:
                _log.error(f"Failed to apply queued rp.db title update for {effect_id}: {e}")
            continue
        # action == "md5"
        remembered_md5 = entry.get("new_md5", "")
        # Recompute the zip's actual md5 from disk — never trust the remembered value
        actual_md5 = _recompute_zip_md5(user_data, effect_id)
        if actual_md5 is None:
            _log.warning(
                f"Flush: zip for {effect_id} not found on disk. "
                f"Skipping (may have been uninstalled or cleared)."
            )
            continue
        if actual_md5 != remembered_md5:
            _log.warning(
                f"Flush: zip md5 for {effect_id} changed since queue time "
                f"(remembered={remembered_md5[:16]}, actual={actual_md5[:16]}). "
                f"Writing actual value — if zip was reverted, install is lost but rp.db stays consistent."
            )
        try:
            _apply_rpdb_update(db_path, effect_id, actual_md5)
            applied += 1
        except PackError as e:
            _log.error(f"Failed to apply queued rp.db update for {effect_id}: {e}")

    pending_path.unlink(missing_ok=True)
    _log.info(f"Flushed {applied}/{len(pending)} pending rp.db updates")
    return applied


def check_install_integrity(capcut_root: Path) -> list[dict]:
    """Check every installed pack for zip/rp.db md5 consistency.

    For each entry in installed.json (GeneralEffect registry), recomputes
    the zip's actual md5 and compares it to the md5 stored in rp.db.
    Returns a list of dicts with mismatch details:
      {pack_id, effect_id, donor_title, zip_md5, rpdb_md5, status}
    status is 'OK', 'MISMATCH', or 'MISSING_ZIP'.
    """
    user_data = capcut_root.parent / "User Data"
    if not user_data.is_dir():
        user_data = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "User Data"

    registry = _read_ge_registry(capcut_root)
    if not registry:
        return []

    # Read rp.db md5 values for all effects
    rpdb_md5s: dict[str, str] = {}
    ressdk_base = user_data / "Cache" / "ressdk_db"
    if ressdk_base.is_dir():
        import sqlite3
        for db_dir in sorted(ressdk_base.iterdir()):
            db_path = db_dir / "rp.db"
            if not db_path.exists():
                continue
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT response_body FROM http_cache")
                for (body,) in cur.fetchall():
                    try:
                        data = json.loads(body)
                        def _find_effect_items(obj):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if k == "effect_item_list" and isinstance(v, list):
                                        yield v
                                    yield from _find_effect_items(v)
                            elif isinstance(obj, list):
                                for v in obj:
                                    yield from _find_effect_items(v)
                        for items in _find_effect_items(data):
                            for item in items:
                                if not isinstance(item, dict):
                                    continue
                                ca = item.get("common_attr", {})
                                eid = str(ca.get("effect_id", ""))
                                if eid:
                                    rpdb_md5s[eid] = ca.get("md5", "")
                    except (json.JSONDecodeError, KeyError):
                        continue
                conn.close()
            except Exception as e:
                _log.warning(f"check_install_integrity: failed to read {db_path}: {e}")

    results = []
    for pack_id, entry in registry.items():
        effect_id = str(entry.get("donor", ""))
        donor_title = entry.get("donor_title", "")
        if not effect_id:
            continue

        # Check donor package format — GESticker donors never render
        effect_dir = user_data / "Cache" / "effect" / effect_id
        try:
            from slots import classify_donor_format, DonorFormat
            fmt = classify_donor_format(effect_dir)
        except Exception:
            fmt = DonorFormat.UNKNOWN
        if fmt is DonorFormat.GESTICKER:
            _log.warning(
                f"Integrity: {pack_id} installed into GESticker donor {effect_id} "
                f"— broken by construction, will never render"
            )
            results.append({
                "pack_id": pack_id, "effect_id": effect_id,
                "donor_title": donor_title,
                "zip_md5": "", "rpdb_md5": "",
                "status": "GESTICKER_DONOR",
            })
            continue

        zip_md5 = _recompute_zip_md5(user_data, effect_id)
        rpdb_md5 = rpdb_md5s.get(effect_id, "")
        if zip_md5 is None:
            results.append({
                "pack_id": pack_id, "effect_id": effect_id,
                "donor_title": donor_title,
                "zip_md5": "", "rpdb_md5": rpdb_md5,
                "status": "MISSING_ZIP",
            })
        elif zip_md5 == rpdb_md5:
            results.append({
                "pack_id": pack_id, "effect_id": effect_id,
                "donor_title": donor_title,
                "zip_md5": zip_md5, "rpdb_md5": rpdb_md5,
                "status": "OK",
            })
        else:
            _log.warning(
                f"Integrity mismatch for {pack_id} (effect {effect_id}): "
                f"zip={zip_md5[:16]} rpdb={rpdb_md5[:16]}"
            )
            results.append({
                "pack_id": pack_id, "effect_id": effect_id,
                "donor_title": donor_title,
                "zip_md5": zip_md5, "rpdb_md5": rpdb_md5,
                "status": "MISMATCH",
            })
    return results


def _apply_rpdb_update(db_path: Path, effect_id: str, new_md5: str) -> None:
    """Actually write to rp.db. Only call when CapCut is NOT running."""
    import sqlite3

    if not db_path.exists():
        raise PackError(f"rp.db not found at {db_path}")

    backup = db_path.with_suffix(".db.packbak")
    if not backup.exists():
        shutil.copy2(db_path, backup)
        _log.info(f"Created rp.db backup at {backup}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute("SELECT rowid, url, response_body FROM http_cache")

        def _find_effect_items(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "effect_item_list" and isinstance(v, list):
                        yield v
                    yield from _find_effect_items(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _find_effect_items(v)

        updated = 0
        for rowid, url, body in cur.fetchall():
            try:
                data = json.loads(body)
                found = False
                for items in _find_effect_items(data):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        ca = item.get("common_attr", {})
                        if str(ca.get("effect_id", "")) == str(effect_id):
                            old_md5 = ca.get("md5", "")
                            ca["md5"] = new_md5
                            found = True
                            _log.rpdb_op(f"UPDATE rowid={rowid}", 1, old_md5, new_md5, True)
                if found:
                    cur.execute(
                        "UPDATE http_cache SET response_body = ? WHERE rowid = ?",
                        (json.dumps(data), rowid),
                    )
                    updated += 1
            except (json.JSONDecodeError, KeyError):
                continue
        conn.commit()
        _log.info(f"rp.db update complete: {updated} rows updated")
    except Exception as e:
        conn.rollback()
        _log.exception(f"rp.db update failed, restoring from backup")
        if backup.exists():
            shutil.copy2(backup, db_path)
        raise PackError(
            f"Something went wrong updating the transition catalog. "
            f"It has been restored from backup. Try again. ({e})"
        )
    finally:
        conn.close()


def _apply_rpdb_title_update(db_path: Path, effect_id: str, new_title: str) -> None:
    """Update the title field for an effect in rp.db http_cache.

    Only call when CapCut is NOT running.
    """
    import sqlite3

    if not db_path.exists():
        raise PackError(f"rp.db not found at {db_path}")

    backup = db_path.with_suffix(".db.packbak")
    if not backup.exists():
        shutil.copy2(db_path, backup)
        _log.info(f"Created rp.db backup at {backup}")

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute("SELECT rowid, response_body FROM http_cache")

        def _find_effect_items(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "effect_item_list" and isinstance(v, list):
                        yield v
                    yield from _find_effect_items(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _find_effect_items(v)

        updated = 0
        for rowid, body in cur.fetchall():
            try:
                data = json.loads(body)
                found = False
                for items in _find_effect_items(data):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        ca = item.get("common_attr", {})
                        if str(ca.get("effect_id", "")) == str(effect_id):
                            old_title = ca.get("title", "")
                            ca["title"] = new_title
                            found = True
                            _log.info(f"Title update: rowid={rowid} '{old_title}' -> '{new_title}'")
                if found:
                    cur.execute(
                        "UPDATE http_cache SET response_body = ? WHERE rowid = ?",
                        (json.dumps(data), rowid),
                    )
                    updated += 1
            except (json.JSONDecodeError, KeyError):
                continue
        conn.commit()
        _log.info(f"rp.db title update complete: {updated} rows updated")
    except Exception as e:
        conn.rollback()
        _log.exception(f"rp.db title update failed, restoring from backup")
        if backup.exists():
            shutil.copy2(backup, db_path)
        raise PackError(
            f"Something went wrong updating the transition title. "
            f"rp.db has been restored from backup. ({e})"
        )
    finally:
        conn.close()

"""ccversion — discover installed CapCut builds and pick the one CCMOD should drive.

CCMOD's shipping helpers are version-tolerant (Qt metaobject by NAME, Cronet exports by NAME, file
edits), so "supporting a version" mostly means: find it, launch IT (never the auto-updating stub),
and know its per-build facts (draft format number, whether donorless packages are known to render).

    python ccversion.py            # table of installed builds + chosen target
    python ccversion.py --json
    python ccversion.py backup 8.9.1     # mirror the build to CCMOD-Backups (1.6 GB for 8.9.1)
    python ccversion.py restore 8.9.1    # put it back if an update removed it

Select a build explicitly with  CCMOD_CAPCUT_VERSION=9.2.0.3931  (prefix ok: "8.9").
Per-build facts live in PROFILES; unknown builds get a conservative "untested" profile and are still
launchable, so a new CapCut release never hard-fails CCMOD.
"""
import json, os, re, sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Facts learned empirically. renders: True proven, False proven broken, None untested.
PROFILES = {
    "8.9.1": {"draft_version": "175.0.0", "renders": True, "preferred": True,
              "note": "reference build: donorless packages render"},
    "9.2.0": {"draft_version": "181.0.0", "renders": True,
              "note": "renders donorless effects (proven 4 Oct) IF packages are rebuilt from this build's own cached Sharpen Edges template; opening a project here bumps its draft to 181 (back up first)"},
}
KEY_DLLS = ("FusionUI.dll", "VECreator.dll", "sscronet.dll", "EffectPlatform.dll", "libGLESv2.dll")
_VER = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def local_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "CapCut"


@dataclass
class Build:
    version: str
    root: Path
    exe: Path
    profile: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)

    @property
    def short(self) -> str:
        return ".".join(self.version.split(".")[:3])

    @property
    def renders(self):
        return self.profile.get("renders")

    @property
    def user_data(self) -> Path:
        return local_root() / "User Data"


def _key(v: str):
    return tuple(int(x) for x in v.split("."))


def installed(apps: Path | None = None) -> list[Build]:
    apps = apps or local_root() / "Apps"
    out = []
    if not apps.is_dir():
        return out
    for d in sorted((p for p in apps.iterdir() if p.is_dir() and _VER.match(p.name)),
                    key=lambda p: _key(p.name)):
        exe = d / "CapCut.exe"
        if not exe.exists():
            continue
        b = Build(d.name, d, exe)
        b.profile = dict(PROFILES.get(b.short, {"draft_version": None, "renders": None,
                                              "note": "untested build"}))
        b.missing = [n for n in KEY_DLLS if not (d / n).exists() and not (d / "VEAngle" / n).exists()]
        out.append(b)
    return out


def current_per_productinfo(apps: Path | None = None):
    """What the auto-updating stub (Apps\\CapCut.exe) would launch."""
    pi = (apps or local_root() / "Apps") / "ProductInfo.xml"
    try:
        m = re.search(r'full_appver value="([\d.]+)"', pi.read_text(encoding="utf-8-sig"))
        return m.group(1) if m else None
    except OSError:
        return None


def pick(want: str | None = None, builds: list[Build] | None = None) -> Build | None:
    """Explicit request > preferred build > newest build known to render > newest build."""
    builds = builds if builds is not None else installed()
    want = want or os.environ.get("CCMOD_CAPCUT_VERSION")
    if want:
        for b in reversed(builds):
            if b.version.startswith(want):
                return b
        return None
    good = [b for b in builds if b.renders]
    pref = [b for b in good if b.profile.get("preferred")]   # safe default until DraftGuard exists
    return (pref or good or builds or [None])[-1]


def backup_dir() -> Path:
    return local_root() / "CCMOD-Backups"


def backup(version: str) -> Path:
    """Mirror Apps/<version> to CCMOD-Backups/<version> (robocopy, resumable). Returns the backup path."""
    import subprocess
    b = pick(version)
    if not b:
        raise SystemExit(f"no installed build matching {version}")
    dst = backup_dir() / b.version
    rc = subprocess.run(["robocopy", str(b.root), str(dst), "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NP"]).returncode
    if rc >= 8:
        raise SystemExit(f"robocopy failed ({rc})")
    return dst


def restore(version: str) -> Path:
    """Put a backed-up build back into Apps/ (use after an update removed/replaced it)."""
    import subprocess
    src = next((p for p in backup_dir().glob("*") if p.name.startswith(version)), None) if backup_dir().is_dir() else None
    if not src:
        raise SystemExit(f"no backup for {version} in {backup_dir()}")
    dst = local_root() / "Apps" / src.name
    rc = subprocess.run(["robocopy", str(src), str(dst), "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NP"]).returncode
    if rc >= 8:
        raise SystemExit(f"robocopy failed ({rc})")
    return dst


def ensure(version: str) -> Build | None:
    """Self-heal after an auto-update: if `version` is no longer installed but a CCMOD backup exists, restore it.
    Returns the build (installed or restored), or None when it is gone and unbacked-up."""
    b = pick(version)
    if b:
        return b
    try:
        restore(version)
    except SystemExit:
        return None
    return pick(version)


def main():
    if len(sys.argv) > 2 and sys.argv[1] in ("backup", "restore", "ensure"):
        if sys.argv[1] == "ensure":
            b = ensure(sys.argv[2]); print("ok" if b else "missing", b.version if b else ""); return
        print(("backup ->" if sys.argv[1] == "backup" else "restored ->"), (backup if sys.argv[1] == "backup" else restore)(sys.argv[2]))
        return
    builds = installed()
    chosen = pick(builds=builds)
    if "--json" in sys.argv:
        print(json.dumps({"stub_version": current_per_productinfo(),
                          "chosen": chosen.version if chosen else None,
                          "builds": [{**asdict(b), "root": str(b.root), "exe": str(b.exe)} for b in builds]},
                         indent=2))
        return
    print(f"stub (auto-update) launches: {current_per_productinfo()}")
    for b in builds:
        r = {True: "renders", False: "BROKEN", None: "untested"}[b.renders]
        mark = "->" if chosen and b.version == chosen.version else "  "
        print(f" {mark} {b.version:<14} draft={b.profile.get('draft_version')}  {r:<8} "
              f"missing={b.missing or '-'}  {b.profile.get('note','')}")
    if not chosen:
        print("no CapCut build found")


if __name__ == "__main__":
    main()

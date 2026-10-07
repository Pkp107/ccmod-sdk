import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ccversion


def test_ensure_restores_missing_build(tmp_path, monkeypatch):
    monkeypatch.setattr(ccversion, "local_root", lambda: tmp_path)
    apps = tmp_path / "Apps"; apps.mkdir()
    bk = tmp_path / "CCMOD-Backups" / "8.9.1.3802"; bk.mkdir(parents=True)
    (bk / "CapCut.exe").write_bytes(b"MZ")
    monkeypatch.setattr(ccversion, "pick", lambda want=None, builds=None: (apps / "8.9.1.3802" / "CapCut.exe").exists() and "found" or None)
    assert ccversion.ensure("8.9.1") == "found"
    assert (apps / "8.9.1.3802" / "CapCut.exe").exists()


def test_ensure_none_without_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(ccversion, "local_root", lambda: tmp_path)
    monkeypatch.setattr(ccversion, "pick", lambda want=None, builds=None: None)
    assert ccversion.ensure("8.9.1") is None

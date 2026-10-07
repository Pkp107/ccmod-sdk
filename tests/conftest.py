"""Keep the test suite off the real CapCut install.

Several code paths fall back to production locations when their preferred path
does not exist:

    packs._ge_registry_path()    capcut_root.parent/"User Data", else
                                 %LOCALAPPDATA%/CapCut/User Data
    packs.check_install_integrity()          same fallback
    slots.resolve_user_data()                same fallback
    ccmod.DEFAULT_CAPCUT_ROOT    hardcoded C:/Users/you/AppData/Local/CapCut/...

capcut_root.parent/"User Data" never exists in a real install (Apps/<version>
sits beside User Data, not above it), so the fallback is the normal path, not
an edge case. A test that passes a tmp_path root and forgets to redirect
LOCALAPPDATA therefore reads the live registry, the live rp.db and the live
cache -- and can pass for the wrong reason. One test in this suite did exactly
that: the real registry happens to hold exactly one entry, so an assertion of
"one result" passed against production data.

The autouse fixture below points LOCALAPPDATA and CCMOD_ROOT at a per-test
temporary directory, so the fallback lands somewhere harmless. Tests that want
the real thing must opt in explicitly with the `live_capcut` marker.
"""
import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REAL_CAPCUT = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Parth\AppData\Local")) / "CapCut"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_capcut: test deliberately reads the real CapCut install",
    )


@pytest.fixture(autouse=True)
def isolate_from_live_capcut(request, tmp_path_factory, monkeypatch):
    """Redirect the production fallbacks into a temp dir for every test."""
    if request.node.get_closest_marker("live_capcut"):
        # Opt-in: leave the environment pointing at the real install.
        yield None
        return

    sandbox = tmp_path_factory.mktemp("capcut_sandbox")
    (sandbox / "CapCut" / "User Data").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(sandbox))
    # Do NOT set CCMOD_ROOT: _install_root() prefers the env var over
    # DEFAULT_CAPCUT_ROOT, so setting it here would override the tests that
    # correctly patch DEFAULT_CAPCUT_ROOT at a tmp tree. Clearing it stops a
    # stray value in the developer's shell from aiming tests at production.
    monkeypatch.delenv("CCMOD_ROOT", raising=False)
    yield sandbox


@pytest.fixture
def assert_live_untouched():
    """Fail if the real install's registry changed during a test."""
    reg = REAL_CAPCUT / "User Data" / "installed.json"
    before = reg.read_bytes() if reg.is_file() else None
    yield
    after = reg.read_bytes() if reg.is_file() else None
    assert before == after, "test modified the real CapCut installed.json"


# ── guard: the real install must survive the suite untouched ────────────

_REAL_DLL = Path(
    r"C:\Users\Parth\AppData\Local\CapCut\Apps\8.9.1.3802\FusionUI.dll"
)


def _dll_digest():
    if not _REAL_DLL.is_file():
        return None
    return hashlib.sha256(_REAL_DLL.read_bytes()).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def real_fusionui_dll_must_not_change():
    """Fail the run if the suite writes to the real FusionUI.dll.

    The theme tests apply and revert real patches. They are supposed to do that
    against a copy in tmp_path, but ccmod resolves its target through
    _install_root() -> DEFAULT_CAPCUT_ROOT, and a test that forgets to patch
    that writes straight into the user's CapCut. It has happened once. The DLL
    has no factory copy beyond the vendor backup, so this is worth a hard stop
    rather than a discovery three sessions later.
    """
    before = _dll_digest()
    yield
    after = _dll_digest()
    if before != after:
        pytest.fail(
            "THE TEST SUITE MODIFIED THE REAL FusionUI.dll.\n"
            f"  before: {before}\n"
            f"  after:  {after}\n"
            "  Restore it with:\n"
            "    copy FusionUI.dll.vendor-original.bak over FusionUI.dll\n"
            "  A theme test is resolving its target through the real "
            "DEFAULT_CAPCUT_ROOT instead of its tmp_path copy.",
            pytrace=False,
        )

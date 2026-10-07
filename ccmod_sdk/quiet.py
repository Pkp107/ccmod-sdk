"""No flashing console windows.

When ccmod runs windowless (pythonw, started from the Loader or at login) every helper it starts (tasklist, powershell, python,
ffmpeg ...) used to pop a console window for a moment. `install()` makes every subprocess started by this Python process
default to CREATE_NO_WINDOW. Callers that pass their own `creationflags` or `startupinfo` keep full control.

It is safe to call more than once, and it does nothing off Windows.
"""
from __future__ import annotations

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
_installed = False


def install() -> bool:
    """Patch subprocess.Popen once. Returns True if the patch is active."""
    global _installed
    if os.name != "nt":
        return False
    if _installed:
        return True
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        if not kwargs.get("creationflags") and kwargs.get("startupinfo") is None:
            kwargs["creationflags"] = CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    _installed = True
    return True


def pythonw() -> str:
    """The windowless interpreter next to the current one (falls back to the current interpreter)."""
    import sys
    from pathlib import Path
    w = Path(sys.executable).with_name("pythonw.exe")
    return str(w if w.exists() else sys.executable)

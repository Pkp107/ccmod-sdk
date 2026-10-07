"""ccmod SDK — build plugins that extend CapCut: effects, UI, themes, engine hooks, tools.

    from ccmod_sdk import Plugin

    class Hello(Plugin):
        def on_load(self):
            self.ctx.ui.inject_qml("MainTimeLineToolBar_QMLTYPE", "import QtQuick 2.15\\nRectangle { ... }")

See docs/reference/SDK.md.
"""
from .backend import Backend, BackendError, FakeBackend, FridaBackend
from . import quiet as _quiet
_quiet.install()                       # helpers never flash a console window (see quiet.py)
from .context import Context
from .loader import Host, Plugin
from .manifest import PERMISSIONS, SDK_VERSION, Manifest, ManifestError

__all__ = ["Plugin", "Host", "Context", "Manifest", "ManifestError", "Backend", "FakeBackend", "FridaBackend",
           "BackendError", "PERMISSIONS", "SDK_VERSION"]
__version__ = SDK_VERSION

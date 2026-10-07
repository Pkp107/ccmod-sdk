---
title: Install
section: Getting started
order: 10
---

# Install

## The easy way

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/) and tick *Add python.exe to PATH* on the first screen.
2. Install **CapCut Desktop 8.9.1** and open it once. (ccmod is built for that version; newer builds can show effects as plain passthrough.)
3. Get ccmod: download it from GitHub as a zip and unpack it anywhere, or `git clone https://github.com/Pkp107/capcut-ccmod.git`.
4. Double-click **`Install ccmod.bat`** in the ccmod folder.

That one script checks everything, installs the Python packages it needs, restores the injection DLL if needed, installs the starter effects and transitions, and puts a **Start ccmod** shortcut on your desktop. It is safe to run again; it only does what's still missing, and it tells you in plain words if something needs your attention.

To start ccmod afterwards, **double-click Start ccmod on your desktop**. It runs with no console windows; the Loader shows whether ccmod is running.

Want to see what setup would do without changing anything?

```bash
python ccmod_setup.py --check
```

## What setup checks

| Step | Meaning |
|---|---|
| Python | 3.10 or newer |
| Python packages | `frida`, `psutil`, `pillow`, `markdown` (from `requirements.txt`) |
| CapCut | a build ccmod can use; 8.9.1.3802 is the reference |
| Injection DLL | `ccmod_inject.dll` is the full build (it restores it from `ccmod_inject.dll.bak2` if needed, with CapCut closed) |
| Starter effects / transitions | built from CapCut's cached templates. If CapCut has never been opened, setup tells you to open it once |
| Desktop shortcut | *Start ccmod* |

!!! note "Sign-in"
    CapCut may show a subscription or sign-in screen when opening a project. That is CapCut's own behaviour and ccmod does not touch it.

## Optional extras

**The Loader** (a window to manage ccmod): needs the .NET 8 SDK to build.

```bash
cd bootstrapper/ccmodloader
dotnet build -c Release
```

The exe lands in `bin/Release/net8.0-windows/ccmodloader.exe`.

**The transition editor** (a separate app for designing transitions): see [Transition editor](transition-editor.html).

## Doing it by hand

If you'd rather run each step yourself:

```bash
pip install -r requirements.txt
python ccversion.py                       # which CapCut builds ccmod found
python scratch/ccfx.py install easedown chromatic vignette glow bloom
python -m ccmod_sdk.transitions install
python ccmod_run.py                       # launch CapCut with ccmod
```

`ccmod_run.py` checks the pinned CapCut build, clears CapCut's cached catalog replies, starts the local catalog helper, loads your plugins, launches CapCut (retrying, because a launch right after a close often exits) and attaches. `python ccmod_run.py autostart` starts ccmod with Windows.

## Verify

```bash
python -m ccmod_sdk list         # your plugins and why any were skipped
python -m pytest                 # the test suite (no CapCut needed)
```

Next: [Quick start](quickstart.html).

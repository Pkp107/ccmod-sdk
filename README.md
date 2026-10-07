# ccmod SDK

An open-source toolkit for building your own effects and transitions for CapCut Desktop, plus a standalone
**transition editor**. ccmod is strictly additive: it never touches the watermark, Pro/subscription features,
accounts, licensing or payment.

> Unofficial and not affiliated with CapCut or ByteDance. Read [DISCLAIMER.md](DISCLAIMER.md) first.

## What is in this repository

| Folder | What it is |
|---|---|
| `ccmod_sdk/` | The Python SDK: plugin manifests and loader, effect/transition **creator** (blocks to GLSL, no code executed), keyframe **expressions**, **timeline** API for draft files, multi-pass effects, UI toolkit, external-app framework (`apps/`) |
| `editor/` | The **transition editor**: a separate C++ / Dear ImGui / Direct3D 11 desktop app with keyframes, 33 easings, a graph editor and a 1:1 preview. Exports a `.ccmodtrans` file |
| `site/` | Source of the documentation site |
| `tests/` | Offline tests (no CapCut needed) |

## What is not in this repository

The runtime that attaches to a running CapCut (process injection, the local catalog proxy, the reverse-engineering
notes and the injection DLL) is not published here. The SDK runs against a fake backend, so everything in this
repository can be developed and tested without CapCut.

## Quick start

```bash
pip install -r requirements.txt pytest
python -m pytest            # offline test suite
```

Build the transition editor (needs Visual Studio Build Tools 2022, "Desktop development with C++"):

```bash
editor\build.bat            # builds editor\bin\ccmod-transition-editor.exe
editor\build_tests.bat      # model and shader tests
```

## Licence

MIT, see [LICENSE](LICENSE). The licence covers only the code and documentation in this repository and grants no
rights in CapCut or ByteDance software, assets or trademarks. Dear ImGui (`editor/third_party/imgui`) is MIT
licensed by Omar Cornut.

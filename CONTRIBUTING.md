# Contributing to CCMOD

Thanks for your interest! CCMOD is research-grade software; contributions that improve reliability,
add effects, or sharpen the docs are very welcome.

## Ground rules

1. **Additive only.** CCMOD never touches the watermark, paid/Pro unlocks, licensing, or payment.
   PRs that circumvent paid features will be rejected — this is non-negotiable (see
   [`DISCLAIMER.md`](DISCLAIMER.md)).
2. **No proprietary content.** Do not commit CapCut/ByteDance code, SDKs, shaders, resource
   packages, databases (`rp.db`, cache dumps), or decompiled sources. Commit only original CCMOD
   code and your own effect packages.
3. **No large binaries or session artifacts.** Screenshots, videos, dump JSONs, and recovered DBs
   stay out of git (see `.gitignore`).

## Setup

- Windows + CapCut 8.9.1.3802, Python 3.11+, `pip install frida frida-tools`.
- Read [`CCMOD-HANDOFF.md`](CCMOD-HANDOFF.md) (what/how) and [`DROID-OPERATIONS.md`](DROID-OPERATIONS.md)
  (driving CapCut, tooling, gotchas) first.

## Authoring an effect

- Effects are donorless GLSL shader packages. Start from `scratch/ccfx.py` (the effect library) and
  the specs in [`docs/reference/`](docs/reference/) (`CCPACK-SPEC.md`, `AUTHORING.md`, `formats.md`).
- Prototype looks in Remotion/React if helpful, then port to CapCut GLSL.

## Pull requests

- Keep changes focused; describe what you tested and how (on-screen proof matters here).
- Match the surrounding code's style.
- By contributing you agree your work is licensed under the repo's [MIT License](LICENSE).

## Reporting

- Bugs / features: use the issue templates.
- Security-sensitive reports: see [`SECURITY.md`](SECURITY.md).

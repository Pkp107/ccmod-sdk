---
title: Contributing
section: Project
order: 40
---

# Contributing

Contributions that improve reliability, add effects/transitions/themes/plugins, or sharpen the docs are welcome.

## Ground rules

1. **Additive only.** No change touching the watermark, Pro unlocks, accounts, licensing or payment. Such PRs are rejected. See [Safety rules](safety.html).
2. **No proprietary content.** Don't commit CapCut/ByteDance code, shaders, resource packages, databases or cache dumps. Only original ccmod code and your own effects.
3. **No large binaries or session artifacts.** Keep screenshots, videos and dumps out of git.

## Workflow

```bash
git clone https://github.com/Pkp107/capcut-ccmod.git
python -m pytest              # must pass; the suite needs no CapCut
```

Add tests next to what you change (`tests/`). Plugin code can be tested with `FakeBackend`.

## Contributing docs

This site is built from `site/pages/*.md` by `site/build.py` (Python `markdown`, no framework). Each page starts with:

```
---
title: Page title
section: Getting started | Using ccmod | Building | Reference | Project
order: 10
---
```

Preview locally:

```bash
pip install markdown
python site/build.py --serve      # http://127.0.0.1:8700
```

Pushing to `master` rebuilds and redeploys it through GitHub Actions.

Admonitions: `!!! note`, `!!! warning`, `!!! danger` (indent the body four spaces).

## Sharing a plugin

A plugin is just a folder. Put it in its own repo with a `plugin.json`, and users drop it into `plugins/`. State clearly in the README which permissions it uses and why.

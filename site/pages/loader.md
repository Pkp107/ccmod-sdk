---
title: The Loader
section: Using ccmod
order: 10
---

# The Loader

`ccmodloader.exe` is ccmod's desktop app. It is a front end over the same Python tools you can run by hand, so everything it does you can also script.

![The Launch page](assets/loader-launch.png)

| Page | What it does |
|---|---|
| **Launch** | Start or stop CapCut with ccmod attached. Shows whether CapCut/ccmod are running and which build will launch. |
| **Builds** | The CapCut builds on this PC, which one ccmod prefers, and whether it is the pinned build. |
| **Plugins** | Every plugin in `plugins/` with its permissions. Toggle on/off. Skipped plugins show *why* (bad manifest, wrong CapCut version). |
| **Effects** | The effect and transition library with covers. **Install / Uninstall**, **set a custom cover image** per tile, **import** a `.ccpack` someone shared, **export** your own. |
| **Themes** | Pick a CapCut theme (applies live while CapCut is open, and is remembered for next launches), or **Revert** to CapCut's own look. |
| **Projects** | CapCut drafts and their format numbers (the Loader guards drafts from format bumps, with backups). |
| **General / About** | Paths, links, version. |

### Effects page

![The Effects page](assets/loader-effects.png)

### Plugins page

![The Plugins page](assets/loader-plugins.png)

## How it talks to Python

The Loader calls `ccmod_api.py` and `ccmod_actions.py`, which print JSON:

```bash
python ccmod_api.py status        # builds, projects, effects, plugins in one document
python ccmod_api.py library       # effects + transitions with installed flags and cover paths
python ccmod_api.py themes
python ccmod_api.py run_status
```

Actions (install, theme apply, launch...) go through `ccmod_actions.ACTIONS`:

| Action | Arguments |
|---|---|
| `install` / `uninstall` | `effect|transition`, key |
| `set-cover` / `reset-cover` | cover key, png path / cover key |
| `plugin` | plugin id, `on|off` |
| `theme-apply` / `theme-revert` | theme id / none |
| `import` / `export` | `.ccpack` path / effect name, output path |
| `launch` / `stop` / `refresh` | none |

So a script, a plugin or an AI agent can do anything the Loader can. The [MCP server](mcp.html) exposes exactly these.

## Custom covers

Each tile's cover is a PNG in the ccmod assets folder (`<key>.png`). ccmod writes defaults once and **never overwrites your edits**. Use the Loader's cover button, or drop your own PNG over the file.

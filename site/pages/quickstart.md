---
title: Quick start
section: Getting started
order: 20
---

# Quick start: ten minutes to your first custom effect

This assumes you finished [Install](install.html).

## 1. Start CapCut with ccmod

```bash
python ccmod_run.py
```

Wait about a minute. CapCut opens; ccmod attaches when an editor is open. Open any project (or make a new one).

## 2. Find the ccmod category

In the editor, open **Effects**. The first category is now **ccmod**, with a second **ccmod Extras** tab for the overflow. Open **Transitions** and you'll see **ccmod** there too.

Tiles look and behave like CapCut's own: hover for the preview name, **drag one onto a clip**, and it renders in the preview and in export.

!!! note "Why the tiles are not marked Pro"
    ccmod borrows *free* stock tiles for its entries (it only reads whether a tile is free, it never changes any licensing data), so your own effects never carry a Pro diamond.

## 3. Use the slider

Select the clip, open the effect's panel on the right. Each effect has its own slider, for example **Ease** on the easing-curve effect. Moving it re-renders live.

## 4. Look around the editor

You'll also see:

- a **ccmod** tab in the top tab row (a native panel listing effects with install/apply),
- buttons your plugins added to the timeline toolbar (e.g. *Scrub*, *3D object*),
- the theme you picked, if any.

## 5. Add a button of your own

Create `plugins/my-first/plugin.json`:

```json
{ "id": "my-first", "name": "My First", "version": "0.1.0", "ccmod": ">=0.1", "capcut": ["*"],
  "entry": "main.py", "provides": ["ui"], "permissions": ["ui", "engine"] }
```

and `plugins/my-first/main.py`:

```python
from ccmod_sdk import Plugin

class MyFirst(Plugin):
    def on_editor_open(self):
        self.ctx.ui.add_button("Say hi", self.hi, where="timeline-toolbar")

    def hi(self):
        self.ctx.log.info("playhead is at %.2fs", self.ctx.engine.playhead_seconds())
```

Restart `ccmod_run.py`. A **Say hi** button appears on the timeline toolbar; clicking it logs the playhead time in your terminal. Full walkthrough: [Your first plugin](first-plugin.html).

## 6. Where to go next

- Write a [custom effect](making-effects.html) or [transition](making-transitions.html)
- Pick or build a [theme](themes.html)
- Connect an AI through [MCP](mcp.html)

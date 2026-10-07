---
title: Command line
section: Reference
order: 20
---

# Command line reference

## Which command do I use?

There are four entry points. Day to day you only need the first.

| I want to... | Use |
|---|---|
| Run ccmod with CapCut | `python ccmod_run.py` |
| Create, check or list **plugins** | `python -m ccmod_sdk ...` |
| Install, export or import **effects and transitions** | `python scratch/ccfx.py ...` (effects), `python -m ccmod_sdk.transitions ...` (transitions), or the Loader |
| Script the Loader's actions (themes, covers, install, launch) or read status as JSON | `python ccmod_api.py ...` |

`ccfx.py` lives in `scratch/` for historical reasons; it is the supported effect tool. Everything the Loader does goes through `ccmod_api.py`, so anything you can click you can script.

## ccmod_run.py: run everything

```bash
python ccmod_run.py              # launch CapCut with ccmod, run until Ctrl+C
python ccmod_run.py autostart    # start with Windows
```

Environment: `ccmod_capcut_version=9.2.0.3931` (prefix OK, for example `8.9`) selects a different CapCut build.

## SDK CLI

```bash
python -m ccmod_sdk new <id> [--dir plugins]     # scaffold a plugin
python -m ccmod_sdk validate <plugin folder>     # check plugin.json
python -m ccmod_sdk list                          # installed plugins, and why any were skipped
python -m ccmod_sdk run [--fake]                  # load plugins against CapCut (or a fake backend)
python -m ccmod_sdk enable <id> | disable <id>
python -m ccmod_sdk permissions                   # what each permission allows
```

## Effects and transitions

```bash
python scratch/ccfx.py list
python scratch/ccfx.py install <name> [<name> ...]
python scratch/ccfx.py uninstall <name>
python scratch/ccfx.py pack <name> out.ccpack         # export
python scratch/ccfx.py installpack in.ccpack          # import
python scratch/ccfx.py apply <project> <name>         # write into a project's first effect

python -m ccmod_sdk.transitions install | list
```

## Creator

```bash
python -m ccmod_sdk.creator blocks                          # every block, range and default (JSON)
python -m ccmod_sdk.creator effect recipe.json [--install]
python -m ccmod_sdk.creator transition recipe.json [--install]
python ccmod_api.py create effect|transition recipe.json
python ccmod_api.py blocks
```

## Builds and projects

```bash
python ccversion.py                    # installed CapCut builds + which one is chosen
python ccversion.py --json
python ccversion.py backup 8.9.1       # mirror the build (1.6 GB) to ccmod-Backups
python ccversion.py restore 8.9.1      # put it back if an auto-update removed it
```

## JSON facade (what the Loader calls)

```bash
python ccmod_api.py status | builds | projects | effects | plugins | library | themes | run_status
python ccmod_api.py install effect pixelate
python ccmod_api.py uninstall transition slide
python ccmod_api.py theme-apply midnight
python ccmod_api.py theme-revert
python ccmod_api.py set-cover <cover_key> <png>
python ccmod_api.py plugin <id> on|off
python ccmod_api.py import <file.ccpack>
python ccmod_api.py export <name> <out.ccpack>
python ccmod_api.py launch | stop | refresh
```

Output is a single JSON document on stdout.

## MCP

```bash
python ccmod_mcp.py       # stdio MCP server (register it with your MCP client)
```

## Tests and docs

```bash
python -m pytest                    # full suite, no CapCut needed
python site/build.py --serve        # build this documentation site and preview at http://127.0.0.1:8700
```

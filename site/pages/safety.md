---
title: Safety rules
section: Project
order: 20
---

# Safety rules and disclaimer

## The one hard rule

**ccmod only adds.** It never touches:

- the watermark,
- Pro / subscription features,
- accounts,
- licensing or payment.

The SDK has no API for any of these and none will be added. A plugin that ships such changes is not accepted. ccmod reads CapCut's free/paid flag on stock tiles only to choose which free tile to borrow, and never writes it.

## Disclaimer

ccmod is independent and unofficial, not affiliated with, endorsed by, or connected to CapCut, ByteDance or Bytedance Pte. Ltd. It is a reverse-engineering research project for educational purposes. It injects into a running process, which may violate CapCut's Terms of Service. Use it only on software you own, at your own risk. No warranty.

## Practical safety

- **Back up projects.** Opening a project in a newer CapCut can bump its format. `ctx.draft.save/restore` and the Loader's Projects page keep snapshots.
- **Permissions are visible.** A plugin's permissions are shown before you enable it. A plugin can only use what its manifest declares. Read it. A plugin with `process` can run programs on your PC, and `network` can alter what CapCut shows.
- **The tool server is local.** It binds `127.0.0.1` and needs a token file only your Windows user can read.
- **Plugins are code.** Only install plugins you trust, like any other software.
- **Disk space.** Each Frida attach leaves temp files; if `%TEMP%` fills up CapCut can hang. `python scratch/_clean_frida_tmp.py` cleans them.

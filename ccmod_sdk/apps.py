"""Declarative external-app integration: describe a program once (how to find it, what commands it offers) and any plugin,
the Loader or an MCP client can run it and get the result into CapCut.

An app spec is a JSON file in apps/ (or registered at runtime with ctx.apps.register):

    {"id": "ffmpeg", "name": "FFmpeg",
     "find": {"exe": "ffmpeg", "env": "CCMOD_FFMPEG", "dirs": ["C:/ffmpeg*/bin"]},
     "commands": {
       "grayscale": {"description": "Remove colour",
                     "args": ["-y", "-i", "{input}", "-vf", "hue=s=0", "{output}"],
                     "inputs":  {"input":  {"type": "file"}},
                     "outputs": {"output": {"ext": ".mp4", "import": true}},
                     "timeout": 900}}}

`{name}` placeholders are filled from the call's inputs (type file/text/number) and from generated output paths; outputs with
"import": true are imported into CapCut's media pool when the command succeeds. Nothing is run through a shell.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,30}$")
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
INPUT_TYPES = ("file", "text", "number")


class AppError(ValueError):
    pass


def validate(spec: dict) -> dict:
    if not isinstance(spec, dict) or not _ID.match(str(spec.get("id", ""))):
        raise AppError("app spec needs an 'id' (lowercase letters, digits, - _)")
    if not spec.get("name"):
        raise AppError("app spec needs a 'name'")
    if not (spec.get("find") or {}).get("exe"):
        raise AppError("app spec needs find.exe (the program name)")
    cmds = spec.get("commands")
    if not isinstance(cmds, dict) or not cmds:
        raise AppError("app spec needs at least one command")
    for cname, c in cmds.items():
        if not _ID.match(cname):
            raise AppError(f"bad command name {cname!r}")
        if not isinstance(c.get("args"), list) or not all(isinstance(a, str) for a in c["args"]):
            raise AppError(f"{cname}: 'args' must be a list of strings")
        ins, outs = c.get("inputs", {}), c.get("outputs", {})
        for k, v in ins.items():
            if v.get("type", "text") not in INPUT_TYPES:
                raise AppError(f"{cname}.{k}: type must be one of {INPUT_TYPES}")
        known = set(ins) | set(outs)
        for a in c["args"]:
            for ph in _PLACEHOLDER.findall(a):
                if ph not in known:
                    raise AppError(f"{cname}: placeholder {{{ph}}} is not declared in inputs or outputs")
        for k, v in outs.items():
            if k in ins:
                raise AppError(f"{cname}: {k!r} is both an input and an output")
            if not str(v.get("ext", "")).startswith("."):
                raise AppError(f"{cname}.{k}: output needs an 'ext' like '.mp4'")
    return spec


def discover(apps_dir: Path | None = None) -> dict[str, dict]:
    """All valid app specs by id (invalid files are skipped)."""
    out: dict[str, dict] = {}
    d = apps_dir or APPS_DIR
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try:
                s = validate(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            out[s["id"]] = s
    return out


def _num(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else repr(f)


def build_command(exe: str, command: dict, inputs: dict, out_dir: Path, stamp: str) -> tuple[list[str], dict[str, Path]]:
    """Fill the args template. Returns (argv, {output name: path}). Raises AppError on missing or invalid inputs."""
    ins = command.get("inputs", {})
    values: dict[str, str] = {}
    for k, spec in ins.items():
        if k not in inputs:
            if "default" in spec:
                values[k] = str(spec["default"])
                continue
            raise AppError(f"missing input {k!r}")
        v, t = inputs[k], spec.get("type", "text")
        if t == "file":
            if not Path(str(v)).is_file():
                raise AppError(f"input {k!r}: file not found: {v}")
            values[k] = str(Path(str(v)).resolve())
        elif t == "number":
            try:
                values[k] = _num(v)
            except (TypeError, ValueError):
                raise AppError(f"input {k!r} must be a number") from None
        else:
            values[k] = str(v)
    extra = set(inputs) - set(ins)
    if extra:
        raise AppError(f"unknown input(s): {', '.join(sorted(extra))}")
    outs: dict[str, Path] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, spec in command.get("outputs", {}).items():
        outs[k] = out_dir / f"{k}_{stamp}{spec['ext']}"
        values[k] = str(outs[k])
    return [exe] + [_PLACEHOLDER.sub(lambda m: values[m.group(1)], a) for a in command["args"]], outs


def stamp() -> str:
    return str(int(time.time() * 1000))

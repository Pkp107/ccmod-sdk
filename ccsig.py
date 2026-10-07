"""ccsig — byte-signature scanner so CCMOD hooks survive CapCut updates (no hardcoded RVAs).

A signature is the first N bytes of a function with every build-specific operand (rip-relative displacements,
call/jmp rel32) wildcarded, stored in signatures.json. `find` scans a build's DLL and returns the function RVA.

    python ccsig.py make  VECreator.dll 0x5d6d2a0 CCEffectClip_setEffectId [--build 8.9.1]
    python ccsig.py find  CCEffectClip_setEffectId [--build 9.2]
    python ccsig.py check                       # resolve every signature in every installed build

    from ccsig import resolve;  rva = resolve("CCEffectClip_setEffectId", build)   # build: ccversion.Build
"""
import json, re, sys
from pathlib import Path

import pefile
import ccversion

SIGFILE = Path(__file__).resolve().parent / "signatures.json"


def _load() -> dict:
    try:
        return json.loads(SIGFILE.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _save(d: dict):
    SIGFILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _sections(pe):
    return [(s.VirtualAddress, s.Misc_VirtualSize, s.PointerToRawData, s.SizeOfRawData, s.Characteristics) for s in pe.sections]


def rva_to_off(pe, rva):
    for va, vs, raw, rs, _ in _sections(pe):
        if va <= rva < va + max(vs, rs):
            return raw + (rva - va)
    raise ValueError(f"rva {rva:#x} not in a section")


def make_signature(dll: Path, rva: int, n: int = 48) -> str:
    """Hex pattern ('?? ' wildcard) of the first ~n bytes at rva, operands that vary by build masked."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    from capstone.x86 import X86_OP_MEM, X86_REG_RIP, X86_OP_IMM
    pe = pefile.PE(str(dll), fast_load=True)
    data = Path(dll).read_bytes()
    off = rva_to_off(pe, rva)
    code = data[off:off + n + 16]
    md = Cs(CS_ARCH_X86, CS_MODE_64); md.detail = True
    mask = bytearray(len(code))          # 1 = wildcard
    pos = 0
    for ins in md.disasm(code, rva):
        if pos >= n:
            break
        for op in ins.operands:
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP and ins.disp_size:
                for i in range(ins.disp_size):
                    mask[pos + ins.disp_offset + i] = 1
        if ins.mnemonic in ("call", "jmp") or ins.mnemonic.startswith("j"):
            if ins.imm_size:
                for i in range(ins.imm_size):
                    mask[pos + ins.imm_offset + i] = 1
        pos += ins.size
    return " ".join("??" if mask[i] else f"{code[i]:02x}" for i in range(pos))


def _regex(sig: str) -> re.Pattern:
    parts = []
    for b in sig.split():
        parts.append(b"." if b == "??" else re.escape(bytes.fromhex(b)))
    return re.compile(b"".join(parts), re.DOTALL)


def scan(dll: Path, sig: str) -> list[int]:
    """All RVAs in executable sections matching the signature."""
    pe = pefile.PE(str(dll), fast_load=True)
    data = Path(dll).read_bytes()
    rx = _regex(sig)
    out = []
    for va, vs, raw, rs, ch in _sections(pe):
        if not ch & 0x20000000:          # IMAGE_SCN_MEM_EXECUTE
            continue
        chunk = data[raw:raw + rs]
        for m in rx.finditer(chunk):
            out.append(va + m.start())
    return out


def resolve(name: str, build=None, dll_name: str | None = None):
    """RVA of the named signature in the given build (default: the picked build); None if not found/ambiguous."""
    sigs = _load()
    ent = sigs.get(name)
    if not ent:
        return None
    build = build or ccversion.pick()
    hits = scan(build.root / (dll_name or ent["dll"]), ent["sig"])
    return hits[0] if len(hits) == 1 else None


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "make":
        dll = Path(sys.argv[2]); rva = int(sys.argv[3], 16); name = sys.argv[4]
        b = ccversion.pick(_arg("--build"))
        path = dll if dll.exists() else b.root / dll.name
        for n in (48, 80, 128, 192):          # grow until the signature is unique
            sig = make_signature(path, rva, n)
            hits = scan(path, sig)
            if len(hits) == 1:
                break
        print(f"{name}: {len(sig.split())} bytes, {len(hits)} match(es) in {path.name}", [hex(h) for h in hits[:4]])
        if len(hits) != 1 or hits[0] != rva:
            sys.exit("[!] signature not unique/consistent — need more bytes (raise n)")
        d = _load(); d[name] = {"dll": path.name, "sig": sig, "ref_build": b.version, "ref_rva": hex(rva)}; _save(d)
        print("stored")
    elif cmd in ("find", "check"):
        d = _load()
        names = [sys.argv[2]] if cmd == "find" and len(sys.argv) > 2 else list(d)
        builds = [ccversion.pick(_arg("--build"))] if _arg("--build") else ccversion.installed()
        for n in names:
            for b in builds:
                try:
                    hits = scan(b.root / d[n]["dll"], d[n]["sig"])
                except Exception as e:
                    hits = f"error {e}"
                print(f"{n:<34} {b.version:<14} -> {[hex(h) for h in hits] if isinstance(hits, list) else hits}"
                      f"   (ref {d[n]['ref_build']} {d[n]['ref_rva']})")


if __name__ == "__main__":
    main()

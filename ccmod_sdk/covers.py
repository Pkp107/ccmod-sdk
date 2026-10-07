"""Default tile covers for our effects. Written to <rules dir>/ccmod-assets/<key>.png ONLY IF MISSING, so replacing a file with
your own art is how a cover is edited (the proxy serves that folder and cache-busts by mtime)."""
import colorsys, json, os, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "plugin-state" / "plugin-data" / "ccmod-assets"
BG = (26, 27, 30)

def _glyph():
    p = os.path.expandvars(r"%LOCALAPPDATA%\CapCut\Apps\8.9.1.3802\Resources\logo_cc.png")
    src = Image.open(p).convert("RGBA"); g = src.convert("L")
    m = Image.eval(g, lambda v: 255 - v)
    m = Image.composite(m, Image.new("L", g.size, 0), src.split()[3].point(lambda v: 255 if v > 200 else 0))
    return m.crop(m.point(lambda v: 255 if v > 128 else 0).getbbox()).rotate(90, expand=True)

def _font(sz):
    for n in ("segoeuib.ttf", "arialbd.ttf"):
        try: return ImageFont.truetype(n, sz)
        except OSError: pass
    return ImageFont.load_default()

def make_cover(key: str, label: str, hue: float, size: int = 256) -> Image.Image:
    S = size * 4
    acc = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.85, 0.95))
    im = Image.new("RGBA", (S, S), BG + (255,)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((S * .05, S * .05, S * .95, S * .95), S * .12, outline=acc, width=S // 60)
    gm = ImageOps.contain(_glyph(), (int(S * .5), int(S * .5)), Image.BICUBIC).filter(ImageFilter.GaussianBlur(S / 450))
    gm = gm.point(lambda v: max(0, min(255, int((v - 115) * 4))))
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0)); glow.paste(Image.new("RGBA", gm.size, acc + (255,)), ((S - gm.width) // 2, int(S * .12)), gm)
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S / 40)))
    im.paste(Image.new("RGBA", gm.size, acc + (255,)), ((S - gm.width) // 2, int(S * .12)), gm)
    name = label.replace("CCMOD ", "")
    f = _font(int(S * .17)); 
    while d.textlength(name, font=f) > S * .84 and f.size > 20: f = _font(f.size - 8)
    d.text((S / 2, S * .80), name, font=f, fill=(255, 255, 255), anchor="mm", stroke_width=S // 55, stroke_fill=(0, 0, 0))
    d.text((S / 2, S * .92), "ccmod", font=_font(int(S * .06)), fill=acc, anchor="mm")
    return im.resize((size, size), Image.LANCZOS)

def ensure_covers(assets: Path = ASSETS, index: Path | None = None) -> dict:
    assets.mkdir(parents=True, exist_ok=True)
    ix = json.loads((index or ROOT / "scratch" / "_ccfx_index.json").read_text(encoding="utf-8"))
    made = {}
    for i, (key, v) in enumerate(ix.items()):
        f = assets / f"{key}.png"
        if not f.exists():
            try:
                make_cover(key, v["label"], (i * 0.083) % 1.0).save(f)
            except OSError:                                  # the CapCut logo (cover glyph) is not available: no cover, tile keeps its own
                continue
        made[key] = f.name
    return made

if __name__ == "__main__":
    print(ensure_covers())

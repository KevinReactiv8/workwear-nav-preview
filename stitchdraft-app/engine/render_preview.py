"""
Render a stitch file as it would look sewn: thread-coloured stitches drawn
with rounded thick lines on a garment-coloured background.

Usage: python render_preview.py file.dst out.png [bg_hex]
"""
import sys
import pyembroidery as pe
from PIL import Image, ImageDraw

SCALE = 8  # px per mm


def render(path, out_path, bg="#3a4147"):
    """path: a stitch file path OR an in-memory EmbPattern (keeps colours)."""
    p = path if isinstance(path, pe.EmbPattern) else pe.read(path)
    xs = [s[0] for s in p.stitches]
    ys = [s[1] for s in p.stitches]
    minx, miny = min(xs), min(ys)
    w = int((max(xs) - minx) / 10 * SCALE) + 40
    h = int((max(ys) - miny) / 10 * SCALE) + 40
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    colors = [t.color for t in p.threadlist] or [0xF5F0E6]
    ci = 0
    prev = None
    for x, y, c in p.stitches:
        px = (x - minx) / 10 * SCALE + 20
        py = (y - miny) / 10 * SCALE + 20
        if c == pe.STITCH:
            if prev is not None:
                col = colors[min(ci, len(colors) - 1)]
                rgb = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
                d.line([prev, (px, py)], fill=rgb, width=3)
            prev = (px, py)
        elif c == pe.COLOR_CHANGE:
            ci += 1
            prev = None
        else:
            prev = None
    img.save(out_path)
    print(f"wrote {out_path} ({w}x{h})")


if __name__ == "__main__":
    render(sys.argv[1],
           sys.argv[2] if len(sys.argv) > 2 else "preview.png",
           sys.argv[3] if len(sys.argv) > 3 else "#3a4147")

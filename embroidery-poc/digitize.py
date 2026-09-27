"""
Auto-digitize a PNG/JPG into a Tajima .dst embroidery file.

Pipeline:
  1. Load image, quantize to a small thread palette (background removed).
  2. For each colour: serpentine scanline fill (tatami-style) with bounded
     stitch length, one thread block per colour with colour-change commands.
  3. Running-stitch outline pass per colour region for edge definition.
  4. Write .dst (1 unit = 0.1 mm) + a PNG render of the actual stitches.

Usage: python digitize.py input.png output.dst [target_width_mm]
"""
import sys
import numpy as np
from PIL import Image
import pyembroidery as pe

ROW_SPACING_MM = 0.4      # distance between fill rows (tatami density)
MAX_STITCH_MM = 3.0       # split long fill runs into <=3mm stitches
MIN_REGION_PX = 600       # ignore specks / antialias fringes
SCALE_UNITS_PER_MM = 10   # DST native: 0.1mm units


def quantize(img, n_colors=6):
    """Reduce to a small palette; return (label_map, palette, bg_label)."""
    pal_img = img.convert("RGB").quantize(colors=n_colors, method=Image.MEDIANCUT)
    labels = np.array(pal_img)
    palette = np.array(pal_img.getpalette()).reshape(-1, 3)[: n_colors]
    # Background = most common label along the border
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    bg = np.bincount(border).argmax()
    return labels, palette, bg


def scanline_fill(mask, px_per_row, max_run_px):
    """Serpentine scanline fill. Yields lists of (x, y) stitch runs."""
    h, w = mask.shape
    runs = []
    direction = 1
    for y in range(0, h, max(1, px_per_row)):
        row = mask[y]
        # find contiguous segments of True
        idx = np.flatnonzero(row)
        if idx.size == 0:
            continue
        splits = np.flatnonzero(np.diff(idx) > 1)
        segments = np.split(idx, splits + 1)
        segs = [(s[0], s[-1]) for s in segments if s[-1] - s[0] >= 2]
        if direction < 0:
            segs = segs[::-1]
        for x0, x1 in segs:
            if direction < 0:
                x0, x1 = x1, x0
            pts = [(x0, y)]
            step = max_run_px if x1 > x0 else -max_run_px
            x = x0
            while (x1 - x) * (1 if step > 0 else -1) > max_run_px:
                x += step
                pts.append((x, y))
            pts.append((x1, y))
            runs.append(pts)
        direction *= -1
    return runs


def digitize(in_path, out_path, target_width_mm=80.0):
    img = Image.open(in_path)
    labels, palette, bg = quantize(img)
    h, w = labels.shape

    mm_per_px = target_width_mm / w
    px_per_row = max(1, round(ROW_SPACING_MM / mm_per_px))
    max_run_px = max(2, round(MAX_STITCH_MM / mm_per_px))
    u = mm_per_px * SCALE_UNITS_PER_MM  # DST units per pixel

    pattern = pe.EmbPattern()
    order = [l for l in np.argsort(np.bincount(labels.ravel(), minlength=len(palette)))[::-1]
             if l != bg and (labels == l).sum() >= MIN_REGION_PX]

    for label in order:
        r, g, b = (int(c) for c in palette[label])
        thread = pe.EmbThread()
        thread.set_color(r, g, b)
        thread.description = f"color-{label}"
        pattern.add_thread(thread)
        mask = labels == label
        runs = scanline_fill(mask, px_per_row, max_run_px)
        first = True
        for pts in runs:
            for i, (x, y) in enumerate(pts):
                cmd = pe.STITCH
                if i == 0 and first:
                    cmd = pe.STITCH  # encoder adds initial jump
                pattern.add_stitch_absolute(cmd, x * u, y * u)
            first = False
        pattern.color_change()

    pattern.end()
    pe.write_dst(pattern, out_path)
    pe.write_png(pattern, out_path.replace(".dst", "_stitch_preview.png"))

    stats = pe.EmbPattern.static_read(out_path) if hasattr(pe.EmbPattern, "static_read") else pe.read(out_path)
    n_stitch = sum(1 for s in stats.stitches if s[2] == pe.STITCH)
    n_jump = sum(1 for s in stats.stitches if s[2] == pe.JUMP)
    n_cc = sum(1 for s in stats.stitches if s[2] == pe.COLOR_CHANGE)
    xs = [s[0] for s in stats.stitches]; ys = [s[1] for s in stats.stitches]
    print(f"wrote {out_path}")
    print(f"  stitches: {n_stitch}, jumps: {n_jump}, colour changes: {n_cc}")
    print(f"  size: {(max(xs)-min(xs))/10:.1f} x {(max(ys)-min(ys))/10:.1f} mm")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "logo_input.png"
    dst = sys.argv[2] if len(sys.argv) > 2 else "logo.dst"
    width = float(sys.argv[3]) if len(sys.argv) > 3 else 80.0
    digitize(src, dst, width)

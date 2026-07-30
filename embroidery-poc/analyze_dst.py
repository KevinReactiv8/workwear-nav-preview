"""
Forensic analyzer for professionally digitized stitch files.

Reads any .dst (or other pyembroidery-supported format) and extracts the
digitizer's parameter choices: satin column widths, satin density, running
stitch lengths, tie-in/tie-off usage, stitch-length histogram, and the
satin/run/fill block breakdown. Point it at a folder of pro files to mine
statistically-grounded defaults for the auto-digitizing engine.

Usage: python analyze_dst.py file1.dst [file2.dst ...]
"""
import sys
import math
import numpy as np
import pyembroidery as pe


def blocks_from(pattern):
    """Split the stitch stream into thread-continuous blocks at TRIM/JUMP."""
    blocks, cur = [], []
    for x, y, c in pattern.stitches:
        if c == pe.STITCH:
            cur.append((x / 10, y / 10))
        elif c in (pe.TRIM, pe.JUMP):
            if len(cur) > 3:
                blocks.append(cur)
            cur = []
    if len(cur) > 3:
        blocks.append(cur)
    return blocks


def analyze(path):
    p = pe.read(path)
    xs = [s[0] for s in p.stitches]
    ys = [s[1] for s in p.stitches]
    n_cc = sum(1 for s in p.stitches if s[2] == pe.COLOR_CHANGE)
    n_trim = sum(1 for s in p.stitches if s[2] == pe.TRIM)

    print(f"== {path}")
    print(f"  size {(max(xs)-min(xs))/10:.1f} x {(max(ys)-min(ys))/10:.1f} mm, "
          f"{sum(1 for s in p.stitches if s[2]==pe.STITCH)} stitches, "
          f"{n_cc + 1} colour(s), {n_trim} trims")

    satin_w, satin_adv, run_lens = [], [], []
    n_satin = n_run = 0
    for b in blocks_from(p):
        v = np.diff(np.array(b), axis=0)
        lens = np.hypot(v[:, 0], v[:, 1])
        dots = (v[:-1] * v[1:]).sum(axis=1)
        reversal = (dots < 0).mean() if len(dots) else 0.0
        if reversal > 0.75 and np.median(lens) > 0.8:
            n_satin += 1
            satin_w.append(np.median(lens))
            pts = np.array(b)
            adv = np.hypot(*(pts[2:] - pts[:-2]).T)  # same-side advance
            satin_adv.append(np.median(adv))
        else:
            n_run += 1
            run_lens.extend(lens)

    if satin_w:
        print(f"  satin: {n_satin} columns, width median "
              f"{np.median(satin_w):.2f}mm (max {max(satin_w):.2f}), "
              f"density ~{np.median(satin_adv):.2f}mm same-side advance")
    if run_lens:
        print(f"  run/underlay/travel: {n_run} blocks, "
              f"{len(run_lens)} stitches, median {np.median(run_lens):.2f}mm")

    # ties: micro-stitches
    prev, tiny = None, 0
    L = []
    for x, y, c in p.stitches:
        if c == pe.STITCH:
            if prev is not None:
                d = math.hypot(x - prev[0], y - prev[1]) / 10
                L.append(d)
                if d < 0.4:
                    tiny += 1
            prev = (x, y)
        else:
            prev = None
    L = np.array(L)
    print(f"  ties (<0.4mm stitches): {tiny}, max stitch {L.max():.1f}mm")
    hist = "  lengths: " + "  ".join(
        f"{lo}-{hi}mm:{((L >= lo) & (L < hi)).sum()}"
        for lo, hi in [(0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4), (4, 13)])
    print(hist)


if __name__ == "__main__":
    for f in sys.argv[1:] or ["Sundays emb.DST"]:
        analyze(f)

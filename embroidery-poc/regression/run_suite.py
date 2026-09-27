"""
Engine regression suite.

Re-digitizes a fixed set of reference designs and compares the resulting
stitch metrics against the committed baseline, so a fix tuned on one design
can never silently break another again (as happened when the CF-logo lobe
work fragmented Cambridge lettering).

Usage, from embroidery-poc/:
    python regression/run_suite.py                  # run + compare
    python regression/run_suite.py --update-baseline  # accept current output

A design FAILS if, vs baseline: stitch count drifts >15%, trims drift >30%
(and by more than 5), the sewn size drifts >2%, the thread-colour count
changes (a colour silently dropped — the crest's purple and green once
were), or a colour sews into its own knockouts (white text reversed out of
a badge — once filled over, and stitch counts alone barely noticed). Previews are written to
regression/out/ for eyeball review — numbers catch drift, eyes catch ugly.
"""
import json
import subprocess
import sys
from pathlib import Path

import pyembroidery as pe
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

HERE = Path(__file__).parent
ENGINE = HERE.parent.parent / "stitchdraft-app" / "engine" / "digitize_pro.py"
BASELINE = HERE / "baseline.json"
OUT = HERE / "out"

# (input file, digitize width mm) — the reference set
DESIGNS = [
    ("cambridge.png", 113.6),
    ("cf_badge.png", 100.0),
    ("01_letter_ladder_sans.png", 100.0),
    ("05_stroke_ladder.png", 100.0),
    ("07_junctions.png", 100.0),
    ("09_touching_elements.png", 100.0),
    ("11_micro_emblems.png", 100.0),
    ("10_composite_crest.png", 100.0),
    ("11_knockout_text.png", 100.0),
]

# a few needle points can legitimately graze a hole edge (ties, satin
# overshoot on tiny counters); a filled-over knockout puts hundreds there
KNOCKOUT_TOLERANCE = 25


def knockout_hits(dst_path, art_path, width):
    """Needle points of each colour landing inside that colour's own holes.
    The engine writes absolute coordinates (0.1mm) in the same mm space as
    extract_regions, so no alignment is needed. Regions map to thread
    blocks in order."""
    sys.path.insert(0, str(ENGINE.parent))
    from digitize_pro import extract_regions
    holes = []
    for _, geom in extract_regions(str(art_path), width):
        # a hole can legitimately hold more art of the same colour (a letter
        # inside a frame) — carve that art out, plus 1mm for its satin
        # border overhang. Only OTHER shapes are carved: the hole's own
        # edge stays tight, so a filled-over knockout still shows up
        hs = []
        for p in geom.geoms:
            for h in p.interiors:
                hp = Polygon(h)
                nested = [q for q in geom.geoms if q is not p and q.within(hp)]
                hole = hp.buffer(-0.3)
                if nested:
                    hole = hole.difference(unary_union(nested).buffer(1.0))
                hs.append(hole)
        holes.append([h for h in hs if not h.is_empty])
    p = pe.read(str(dst_path))
    block, hits = 0, 0
    for x, y, cmd in p.stitches:
        if cmd == pe.COLOR_CHANGE:
            block += 1
        elif cmd == pe.STITCH and block < len(holes):
            pt = Point(x / 10, y / 10)
            hits += sum(1 for h in holes[block] if h.contains(pt))
    return hits


def metrics(dst_path):
    p = pe.read(str(dst_path))
    xs = [s[0] for s in p.stitches]
    ys = [s[1] for s in p.stitches]
    return {
        "stitches": sum(1 for s in p.stitches if s[2] == pe.STITCH),
        "trims": sum(1 for s in p.stitches if s[2] == pe.TRIM),
        "colours": sum(1 for s in p.stitches if s[2] == pe.COLOR_CHANGE) + 1,
        "w_mm": round((max(xs) - min(xs)) / 10, 1),
        "h_mm": round((max(ys) - min(ys)) / 10, 1),
    }


def main():
    update = "--update-baseline" in sys.argv
    OUT.mkdir(exist_ok=True)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    results, failures = {}, []

    for name, width in DESIGNS:
        dst = OUT / (Path(name).stem + ".dst")
        r = subprocess.run(
            [sys.executable, str(ENGINE), str(HERE / "inputs" / name),
             str(dst), str(width)],
            capture_output=True, text=True, timeout=420,
            cwd=str(ENGINE.parent))
        if r.returncode != 0 or not dst.exists():
            failures.append(f"{name}: engine error — "
                            f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '?'}")
            continue
        m = metrics(dst)
        m["knockout_hits"] = knockout_hits(dst, HERE / "inputs" / name, width)
        results[name] = m
        b = baseline.get(name)
        if b and not update:
            msgs = []
            if abs(m["stitches"] - b["stitches"]) > 0.15 * b["stitches"]:
                msgs.append(f"stitches {b['stitches']} -> {m['stitches']}")
            if abs(m["trims"] - b["trims"]) > max(0.30 * b["trims"], 5):
                msgs.append(f"trims {b['trims']} -> {m['trims']}")
            if abs(m["w_mm"] - b["w_mm"]) > 0.02 * b["w_mm"]:
                msgs.append(f"width {b['w_mm']} -> {m['w_mm']}mm")
            if m["colours"] != b["colours"]:
                msgs.append(f"colours {b['colours']} -> {m['colours']}")
            kb = b.get("knockout_hits", 0)
            if m["knockout_hits"] > max(1.5 * kb, kb + KNOCKOUT_TOLERANCE):
                msgs.append(f"stitches inside knockouts {b.get('knockout_hits', 0)} "
                            f"-> {m['knockout_hits']}")
            if msgs:
                failures.append(f"{name}: " + ", ".join(msgs))
        status = "BASE" if not b else ("DRIFT" if any(
            f.startswith(name + ":") for f in failures) else "ok")
        print(f"  {name:32s} {m['stitches']:6d} st {m['trims']:4d} trims "
              f"{m['w_mm']:6.1f}x{m['h_mm']:.1f}mm {m['colours']}col "
              f"{m['knockout_hits']:3d}ko  [{status}]")

    if update or not baseline:
        BASELINE.write_text(json.dumps(results, indent=2))
        print(f"\nbaseline written: {len(results)} designs")
        return 0
    if failures:
        print("\nFAILURES (check regression/out/ previews before accepting):")
        for f in failures:
            print("  " + f)
        return 1
    print("\nall designs within baseline tolerances")
    return 0


if __name__ == "__main__":
    sys.exit(main())

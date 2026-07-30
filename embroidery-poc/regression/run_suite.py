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
(and by more than 5), or the sewn size drifts >2%. Previews are written to
regression/out/ for eyeball review — numbers catch drift, eyes catch ugly.
"""
import json
import subprocess
import sys
from pathlib import Path

import pyembroidery as pe

HERE = Path(__file__).parent
ENGINE = HERE.parent / "digitize_pro.py"
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
]


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
            if msgs:
                failures.append(f"{name}: " + ", ".join(msgs))
        status = "BASE" if not b else ("DRIFT" if any(
            f.startswith(name + ":") for f in failures) else "ok")
        print(f"  {name:32s} {m['stitches']:6d} st {m['trims']:4d} trims "
              f"{m['w_mm']:6.1f}x{m['h_mm']:.1f}mm  [{status}]")

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

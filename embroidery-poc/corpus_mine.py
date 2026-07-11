"""
Batch-mine a folder of professionally digitized stitch files into a
parameter profile for the auto-digitizing engine.

Walks a directory tree (extracting any .zip archives it finds), analyzes
every stitch file pyembroidery can read (.dst, .exp, .pes, .jef, .vp3, ...),
and aggregates the digitizers' choices: satin widths and densities, run
stitch lengths, trims per 1000 stitches, colour counts, design sizes.
Writes pro_profile.json with the measured medians — drop-in values for
digitize_pro.py's parameter block — plus a per-file table.

Usage: python corpus_mine.py /path/to/folder [profile_out.json]
"""
import sys
import json
import zipfile
from pathlib import Path
import numpy as np
import pyembroidery as pe

STITCH_EXTS = {".dst", ".exp", ".pes", ".jef", ".vp3", ".xxx", ".pec",
               ".sew", ".hus", ".pcs", ".tbf", ".u01", ".ksm"}


def blocks_from(pattern):
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


def analyze_file(path):
    try:
        p = pe.read(str(path))
    except Exception as e:
        return {"file": path.name, "error": str(e)}
    if not p.stitches:
        return {"file": path.name, "error": "no stitches"}
    xs = [s[0] for s in p.stitches]
    ys = [s[1] for s in p.stitches]
    n_stitch = sum(1 for s in p.stitches if s[2] == pe.STITCH)
    if n_stitch < 50:
        return {"file": path.name, "error": "too few stitches"}

    satin_w, satin_adv, run_lens = [], [], []
    for b in blocks_from(p):
        v = np.diff(np.array(b), axis=0)
        lens = np.hypot(v[:, 0], v[:, 1])
        dots = (v[:-1] * v[1:]).sum(axis=1)
        reversal = (dots < 0).mean() if len(dots) else 0.0
        if reversal > 0.75 and np.median(lens) > 0.8:
            satin_w.extend(lens.tolist())
            pts = np.array(b)
            satin_adv.extend(np.hypot(*(pts[2:] - pts[:-2]).T).tolist())
        else:
            run_lens.extend(lens.tolist())

    return {
        "file": path.name,
        "stitches": n_stitch,
        "size_mm": [round((max(xs) - min(xs)) / 10, 1),
                    round((max(ys) - min(ys)) / 10, 1)],
        "colours": sum(1 for s in p.stitches if s[2] == pe.COLOR_CHANGE) + 1,
        "trims_per_1k": round(1000 * sum(1 for s in p.stitches
                                         if s[2] == pe.TRIM) / n_stitch, 1),
        "satin_width_med": round(float(np.median(satin_w)), 2) if satin_w else None,
        "satin_width_p95": round(float(np.percentile(satin_w, 95)), 2) if satin_w else None,
        "satin_density": round(float(np.median(satin_adv)), 2) if satin_adv else None,
        "satin_share": round(len(satin_w) / max(len(satin_w) + len(run_lens), 1), 2),
        "run_len_med": round(float(np.median(run_lens)), 2) if run_lens else None,
    }


def mine(root, profile_out="pro_profile.json"):
    root = Path(root)
    # surface any zips first
    for z in root.rglob("*.zip"):
        dest = z.with_suffix("")
        if not dest.exists():
            try:
                zipfile.ZipFile(z).extractall(dest)
                print(f"extracted {z.name}")
            except Exception as e:
                print(f"could not extract {z.name}: {e}")

    results = []
    for f in sorted(root.rglob("*")):
        if f.suffix.lower() in STITCH_EXTS and f.is_file():
            results.append(analyze_file(f))

    ok = [r for r in results if "error" not in r]
    bad = [r for r in results if "error" in r]
    print(f"\nanalyzed {len(ok)} stitch files ({len(bad)} unreadable)")
    for r in bad:
        print(f"  skipped {r['file']}: {r['error']}")
    if not ok:
        return

    def agg(key):
        vals = [r[key] for r in ok if r.get(key) is not None]
        return round(float(np.median(vals)), 2) if vals else None

    profile = {
        "files_analyzed": len(ok),
        "satin_density_mm": agg("satin_density"),
        "satin_width_median_mm": agg("satin_width_med"),
        "satin_width_p95_mm": agg("satin_width_p95"),
        "satin_share_of_stitches": agg("satin_share"),
        "run_stitch_len_mm": agg("run_len_med"),
        "trims_per_1k_stitches": agg("trims_per_1k"),
        "per_file": ok,
    }
    with open(profile_out, "w") as f:
        json.dump(profile, f, indent=2)
    print(f"\n== corpus profile (medians across {len(ok)} files) ==")
    for k, v in profile.items():
        if k != "per_file":
            print(f"  {k}: {v}")
    print(f"\nwrote {profile_out}")


if __name__ == "__main__":
    mine(sys.argv[1] if len(sys.argv) > 1 else ".",
         sys.argv[2] if len(sys.argv) > 2 else "pro_profile.json")

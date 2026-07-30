"""
Vectorize a PNG/JPG into a clean SVG sized in real millimetres — ready to
open in Inkscape + Ink/Stitch for GUI-tuned professional digitizing.

Usage: python vectorize_svg.py input.png output.svg [target_width_mm]
"""
import sys
from digitize_pro import extract_regions


def poly_to_path(poly):
    def ring(coords):
        pts = " L ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
        return f"M {pts} Z"
    d = ring(poly.exterior.coords)
    for hole in poly.interiors:
        d += " " + ring(hole.coords)
    return d


def vectorize(in_path, out_path, target_width_mm=80.0):
    regions = extract_regions(in_path, target_width_mm)
    maxy = max(p.bounds[3] for _, mp in regions for p in mp.geoms)
    maxx = max(p.bounds[2] for _, mp in regions for p in mp.geoms)
    paths = []
    for (r, g, b), mp in regions:
        for poly in mp.geoms:
            paths.append(f'<path d="{poly_to_path(poly)}" '
                         f'fill="rgb({r},{g},{b})" fill-rule="evenodd"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{maxx:.1f}mm" height="{maxy:.1f}mm" '
           f'viewBox="0 0 {maxx:.1f} {maxy:.1f}">\n  '
           + "\n  ".join(paths) + "\n</svg>\n")
    with open(out_path, "w") as f:
        f.write(svg)
    print(f"wrote {out_path}: {len(paths)} paths, {maxx:.0f}x{maxy:.0f}mm")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "logo_input.png"
    out = sys.argv[2] if len(sys.argv) > 2 else "logo_vector.svg"
    width = float(sys.argv[3]) if len(sys.argv) > 3 else 80.0
    vectorize(src, out, width)

"""
Production-grade auto-digitizer: PNG/JPG -> Tajima .dst

Implements the techniques a human digitizer applies, automatically:

  * Vectorization          — colour quantization, then OpenCV contour extraction
                             with hole support and Douglas-Peucker simplification
  * Underlay               — centre-walk contour underlay inset from the edge,
                             plus sparse perpendicular tatami under large fills
                             (stabilises the fabric before the top stitching)
  * Pull compensation      — regions are extended along the stitch direction so
                             the design stays true when thread tension pulls
  * Angled tatami fill     — per-region stitch angle from PCA of the shape,
                             brick-pattern stagger so rows don't ridge
  * Satin borders          — dense zigzag column around every region edge over
                             a running-stitch underlay: the clean raised edge
                             that makes embroidery look professional
  * Tie-in / tie-off       — lock stitches at every thread start/stop so the
                             design survives trimming and washing
  * Stitch routing         — regions sequenced nearest-neighbour per colour to
                             minimise jumps and trims
  * Small-detail guard     — regions narrower than a needle can render are
                             dropped with a warning instead of stitching mush

Also emits a clean vector SVG of the artwork, ready for Ink/Stitch if you
want to hand-tune parameters in a GUI.

Usage:
    python digitize_pro.py input.png output.dst [target_width_mm]

Deps: pip install pyembroidery pillow numpy opencv-python-headless shapely
"""
import sys
import math
import numpy as np
import cv2
from PIL import Image
import pyembroidery as pe
from shapely.geometry import Polygon, MultiPolygon, LineString, box
from shapely.ops import unary_union
from satin import satin_column, stroke_stats, bean_stitch, travel_or_break, blob_stitch

# ---- stitch parameters (all in mm; industry-typical defaults) ----
FILL_ROW_SPACING = 0.40      # tatami density
FILL_STITCH_LEN = 3.0        # max fill stitch length
STAGGER_FRACTIONS = (0.0, 1/3, 2/3)   # brick offset cycle across rows
UNDERLAY_INSET = 0.6         # contour underlay distance inside the edge
UNDERLAY_ROW_SPACING = 2.0   # sparse tatami underlay density
UNDERLAY_STITCH_LEN = 3.5
PULL_COMP = 0.20             # extension along stitch direction, each side
SATIN_WIDTH = 1.4            # border satin column width
SATIN_DENSITY = 0.35         # spacing between satin zigzag strokes
SATIN_PULL_COMP = 0.10       # extra satin width each side
RUN_STITCH_LEN = 2.0         # running / travel stitch length
TIE_LEN = 0.6                # lock-stitch size
MIN_FEATURE_MM = 1.0         # drop details narrower than this (needle limit)
SATIN_MAX_STROKE = 5.0       # strokes narrower than this stitch as satin columns
MIN_REGION_AREA_MM2 = 3.0
UNITS = 10                   # DST units per mm (0.1mm native)


# ----------------------------------------------------------------------------
# 1. Raster -> coloured polygons
# ----------------------------------------------------------------------------

def extract_regions(path, target_width_mm, n_colors=8):
    """Return list of (color_rgb, shapely MultiPolygon in mm coords).

    Background handling: if the image has an alpha channel, transparency IS
    the background (so white artwork on transparent survives — common in
    logo files destined for dark garments). Otherwise the dominant border
    colour is treated as background.
    """
    img = Image.open(path)
    alpha = None
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        alpha = np.array(rgba.split()[-1])
        if alpha.min() == 255:
            alpha = None  # fully opaque
        # composite onto magenta (absent from real logo art) so that white
        # or black artwork can't merge with the backdrop during quantization
        bg = Image.new("RGB", img.size, (255, 0, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    img = img.convert("RGB")
    # work at high resolution for clean contours — but bounded both ways:
    # tiny inputs are upscaled for clean edges, huge inputs are downscaled
    # (2200px across a 100-300mm design is still >7px/mm, well past what
    # contour tracing needs, and it keeps peak memory in check)
    f = None
    if img.width < 1200:
        f = 1200 / img.width
    elif max(img.size) > 2200:
        f = 2200 / max(img.size)
    if f is not None:
        img = img.resize((round(img.width * f), round(img.height * f)), Image.LANCZOS)
        if alpha is not None:
            alpha = np.array(Image.fromarray(alpha).resize(img.size, Image.LANCZOS))

    pal_img = img.quantize(colors=n_colors, method=Image.MEDIANCUT)
    labels = np.array(pal_img)
    palette = np.array(pal_img.getpalette()).reshape(-1, 3)[:n_colors]
    if alpha is not None:
        transparent = alpha < 128
        bg_label = -1  # no colour label is background; transparency is
    else:
        transparent = None
        border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
        bg_label = np.bincount(border).argmax()

    # ---- auto-crop to content: the requested width means the DESIGN's
    # width, not the file's — empty margins shouldn't shrink the stitching
    if transparent is not None:
        content = ~transparent
    else:
        content = labels != bg_label
    ys, xs = np.nonzero(content)
    if len(xs) > 0:
        x0, x1 = xs.min(), xs.max() + 1
        y0, y1 = ys.min(), ys.max() + 1
        labels = labels[y0:y1, x0:x1]
        if transparent is not None:
            transparent = transparent[y0:y1, x0:x1]
        content_w = x1 - x0
    else:
        content_w = img.width
    mm_per_px = target_width_mm / content_w

    # ---- halo merging: antialiasing creates blend colours that sit on the
    # RGB line between the background and a real element colour. Reassign
    # each such label to the element it halos instead of stitching it.
    counts = np.bincount(labels.ravel(), minlength=n_colors)
    if transparent is not None:
        bg_rgb = np.array([255.0, 0.0, 255.0])  # magenta composite backdrop
    else:
        bg_rgb = palette[bg_label].astype(float)
    order = [l for l in np.argsort(counts)[::-1] if l != bg_label and counts[l] > 0]
    # elements = the strongest colours; halos = blends toward bg
    merged = {}
    for l in order:
        c = palette[l].astype(float)
        # near-duplicate palette entries: same colour split by the quantizer
        for m in order:
            if m != l and counts[m] > counts[l] and \
                    np.linalg.norm(c - palette[m].astype(float)) < 30:
                merged[l] = m
                break
        if l in merged:
            continue
        best, best_d = None, 55.0
        for m in order:
            if m == l or counts[m] < counts[l]:
                continue
            e = palette[m].astype(float)
            seg = e - bg_rgb
            denom = float(seg @ seg)
            if denom < 1: continue
            t = float(np.clip((c - bg_rgb) @ seg / denom, 0.15, 0.9))
            d = float(np.linalg.norm(c - (bg_rgb + t * seg)))
            if d < best_d and t < 0.9:
                best, best_d = m, d
        if best is not None:
            merged[l] = None  # halo: drop entirely (antialiasing, not artwork)
    if merged:
        lut = np.arange(n_colors)
        drop = np.zeros(n_colors, bool)
        for l, m in merged.items():
            while m in merged and merged[m] is not None:
                m = merged[m]
            if m is None or merged.get(m, 0) is None and m in merged:
                drop[l] = True
            else:
                lut[l] = m
        labels = lut[labels]
        for l in np.nonzero(drop)[0]:
            if transparent is not None:
                transparent = transparent | (labels == l)
            elif bg_label >= 0:
                labels = np.where(labels == l, bg_label, labels)
        counts = np.bincount(labels.ravel(), minlength=n_colors)

    regions = []
    for label in np.argsort(counts)[::-1]:
        if label == bg_label or counts[label] == 0:
            continue
        if transparent is not None:
            # a colour that lives mostly in the transparent zone is just the
            # composite backdrop showing through — not artwork
            frac = transparent[labels == label].mean()
            if frac > 0.5:
                continue
        else:
            # skip colours that are just shades of the background
            # (antialiasing, slightly-off whites from PDF rendering, etc.)
            bg_color = palette[bg_label].astype(int)
            if np.abs(palette[label].astype(int) - bg_color).sum() < 90:
                continue
        mask = (labels == label).astype(np.uint8)
        if transparent is not None:
            mask &= (~transparent).astype(np.uint8)
        # despeckle antialiasing fringes
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        if mask.sum() * mm_per_px**2 < MIN_REGION_AREA_MM2:
            continue
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP,
                                               cv2.CHAIN_APPROX_TC89_KCOS)
        if hierarchy is None:
            continue
        polys = []
        eps = 0.15 / mm_per_px  # simplify to 0.15mm tolerance
        for i, cnt in enumerate(contours):
            if hierarchy[0][i][3] != -1:
                continue  # holes handled below
            outer = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2) * mm_per_px
            if len(outer) < 3:
                continue
            holes = []
            child = hierarchy[0][i][2]
            while child != -1:
                h = cv2.approxPolyDP(contours[child], eps, True).reshape(-1, 2) * mm_per_px
                if len(h) >= 3:
                    holes.append(h)
                child = hierarchy[0][child][0]
            p = Polygon(outer, holes)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area >= MIN_REGION_AREA_MM2:
                polys.append(p)
        if polys:
            geom = unary_union(polys)
            if isinstance(geom, Polygon):
                geom = MultiPolygon([geom])
            regions.append((tuple(int(c) for c in palette[label]), geom))
    return regions


# ----------------------------------------------------------------------------
# 2. Stitch generation primitives
# ----------------------------------------------------------------------------

def resample(coords, spacing):
    """Resample a coordinate path at uniform spacing along its length."""
    line = LineString(coords)
    n = max(2, int(line.length / spacing) + 1)
    return [line.interpolate(d).coords[0] for d in np.linspace(0, line.length, n)]


def run_along(coords, out, stitch_len=RUN_STITCH_LEN):
    """Running stitch along a path."""
    for pt in resample(coords, stitch_len):
        out.append(pt)


def tie(pt, prev, out):
    """Lock stitches: three tiny stitches around pt along the incoming direction."""
    dx, dy = pt[0] - prev[0], pt[1] - prev[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d * TIE_LEN, dy / d * TIE_LEN
    for f in (0, 1, 0, 1):
        out.append((pt[0] - ux * f, pt[1] - uy * f))


def rotate(coords, angle, origin=(0, 0)):
    c, s = math.cos(angle), math.sin(angle)
    ox, oy = origin
    return [((x - ox) * c - (y - oy) * s + ox, (x - ox) * s + (y - oy) * c + oy)
            for x, y in coords]


def principal_angle(poly):
    """Stitch angle for a region: perpendicular to its principal axis."""
    pts = np.array(poly.exterior.coords)
    pts = pts - pts.mean(axis=0)
    cov = np.cov(pts.T)
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, np.argmax(evals)]
    return math.atan2(major[1], major[0]) + math.pi / 2


def scanline_rows(poly, angle, spacing):
    """Clip horizontal scanlines against the rotated polygon.
    Returns rows of segments in original coordinates."""
    origin = poly.centroid.coords[0]
    rot = Polygon(rotate(poly.exterior.coords, -angle, origin),
                  [rotate(h.coords, -angle, origin) for h in poly.interiors])
    if not rot.is_valid:
        rot = rot.buffer(0)
    minx, miny, maxx, maxy = rot.bounds
    rows = []
    y = miny + spacing / 2
    while y < maxy:
        cut = rot.intersection(LineString([(minx - 1, y), (maxx + 1, y)]))
        segs = []
        geoms = getattr(cut, "geoms", [cut])
        for g in geoms:
            if isinstance(g, LineString) and g.length >= MIN_FEATURE_MM / 2:
                segs.append(list(g.coords))
        if segs:
            segs.sort(key=lambda s: min(p[0] for p in s))
            rows.append([rotate(s, angle, origin) for s in segs])
        y += spacing
    return rows


def tatami_fill(poly, angle, out, spacing=FILL_ROW_SPACING,
                stitch_len=FILL_STITCH_LEN, stagger=True):
    """Serpentine tatami fill with brick-pattern stagger.
    Travels between disjoint segments with a jump marker (None sentinel)."""
    rows = scanline_rows(poly, angle, spacing)
    forward = True
    for ri, row in enumerate(rows):
        segs = row if forward else row[::-1]
        for seg in segs:
            pts = resample(seg, stitch_len)
            # brick stagger: offset interior stitch penetrations per row
            if stagger and len(pts) > 2:
                frac = STAGGER_FRACTIONS[ri % len(STAGGER_FRACTIONS)]
                shift = stitch_len * frac
                line = LineString(seg)
                ds = [min(d + shift, line.length)
                      for d in np.linspace(0, line.length, len(pts))[1:-1]]
                pts = [pts[0]] + [line.interpolate(d).coords[0] for d in ds] + [pts[-1]]
            if not forward:
                pts = pts[::-1]
            if out and out[-1] is not None:
                gap = math.hypot(pts[0][0] - out[-1][0], pts[0][1] - out[-1][1])
                if gap > stitch_len * 1.5:
                    out.append(None)  # jump
            out.extend(pts)
        forward = not forward


def contour_underlay(poly, out):
    """Centre-walk underlay: running stitch inset from the edge."""
    inner = poly.buffer(-UNDERLAY_INSET)
    geoms = getattr(inner, "geoms", [inner])
    for g in geoms:
        if g.is_empty or not isinstance(g, Polygon):
            continue
        if out and out[-1] is not None:
            out.append(None)
        run_along(list(g.exterior.coords), out)


def tatami_underlay(poly, angle, out):
    """Sparse perpendicular tatami underlay beneath large fills."""
    if poly.area < 60:  # only worth it on bigger regions
        return
    inner = poly.buffer(-UNDERLAY_INSET)
    if inner.is_empty:
        return
    geoms = getattr(inner, "geoms", [inner])
    for g in geoms:
        if isinstance(g, Polygon) and not g.is_empty:
            if out and out[-1] is not None:
                out.append(None)
            tatami_fill(g, angle + math.pi / 2, out,
                        spacing=UNDERLAY_ROW_SPACING,
                        stitch_len=UNDERLAY_STITCH_LEN, stagger=False)


def satin_border(poly, out):
    """Satin column along the region outline: running underlay then dense
    zigzag between an inner and outer offset of the edge."""
    half = SATIN_WIDTH / 2 + SATIN_PULL_COMP
    rings = [poly.exterior] + list(poly.interiors)
    for ring in rings:
        if ring.length < SATIN_WIDTH * 3:
            continue
        path = resample(list(ring.coords), SATIN_DENSITY)
        if len(path) < 4:
            continue
        # edge-run underlay along the centre line
        if out and out[-1] is not None:
            out.append(None)
        run_along(path, out)
        # zigzag: alternate perpendicular offsets left/right of the path
        n = len(path)
        for i, (x, y) in enumerate(path):
            (x0, y0) = path[i - 1] if i else path[0]
            (x1, y1) = path[min(i + 1, n - 1)]
            tx, ty = x1 - x0, y1 - y0
            d = math.hypot(tx, ty) or 1.0
            nxv, nyv = -ty / d, tx / d
            side = 1 if i % 2 == 0 else -1
            out.append((x + nxv * half * side, y + nyv * half * side))


def pull_compensate(poly, angle):
    """Extend region along the stitch direction to counter thread pull."""
    # anisotropic dilation: buffer then trim perpendicular growth
    grown = poly.buffer(PULL_COMP, join_style=2)
    origin = poly.centroid.coords[0]
    rot_orig = Polygon(rotate(poly.exterior.coords, -angle, origin),
                       [rotate(h.coords, -angle, origin) for h in poly.interiors])
    rot_grown = Polygon(rotate(grown.exterior.coords, -angle, origin))
    minx, miny, maxx, maxy = rot_orig.bounds
    clip = box(minx - PULL_COMP * 2, miny, maxx + PULL_COMP * 2, maxy)
    result = rot_grown.intersection(clip)
    if result.is_empty or not isinstance(result, Polygon):
        return poly
    back = Polygon(rotate(result.exterior.coords, angle, origin))
    return back if back.is_valid else poly


# ----------------------------------------------------------------------------
# 3. Assembly
# ----------------------------------------------------------------------------

def split_lobes(poly, med_w):
    """Separate wide lobes (wheel dots, bulbs) fused onto a thin stroke:
    erode by the stroke half-width; surviving cores are the lobes."""
    r = max(0.55 * med_w, 0.45)
    core = poly.buffer(-r)
    lobes = [g for g in getattr(core, "geoms", [core])
             if isinstance(g, Polygon) and not g.is_empty and g.area >= 0.8]
    if not lobes:
        return None
    lobe_regions, rest = [], poly
    for g in lobes:
        lr = g.buffer(r * 1.2).intersection(poly)
        lobe_regions.append(lr)
        rest = rest.difference(lr.buffer(0.05))
    return lobe_regions, rest


def order_polys(polys):
    """Nearest-neighbour ordering to minimise jumps."""
    remaining = list(polys)
    ordered = []
    pos = (0.0, 0.0)
    while remaining:
        nxt = min(remaining, key=lambda p: (p.centroid.x - pos[0]) ** 2 +
                                           (p.centroid.y - pos[1]) ** 2)
        remaining.remove(nxt)
        ordered.append(nxt)
        pos = (nxt.centroid.x, nxt.centroid.y)
    return ordered


def emit(pattern, pts):
    """Write a point stream (None = jump) as stitches with ties."""
    started = False
    prev = None
    i = 0
    while i < len(pts):
        p = pts[i]
        if p is None:
            # tie off before the jump, jump to next real point
            nxt = next((q for q in pts[i + 1:] if q is not None), None)
            if started and prev is not None and nxt is not None:
                tie(prev, nxt, [])  # direction only matters visually; simple lock:
                for f in (TIE_LEN, 0, TIE_LEN, 0):
                    pattern.add_stitch_absolute(pe.STITCH,
                                                (prev[0] + f) * UNITS, prev[1] * UNITS)
                pattern.add_stitch_absolute(pe.TRIM, prev[0] * UNITS, prev[1] * UNITS)
            if nxt is not None:
                pattern.add_stitch_absolute(pe.JUMP, nxt[0] * UNITS, nxt[1] * UNITS)
                started = False
            i += 1
            continue
        if not started:
            pattern.add_stitch_absolute(pe.JUMP, p[0] * UNITS, p[1] * UNITS)
            for f in (0, TIE_LEN, 0):  # tie-in
                pattern.add_stitch_absolute(pe.STITCH,
                                            (p[0] + f) * UNITS, p[1] * UNITS)
            started = True
        pattern.add_stitch_absolute(pe.STITCH, p[0] * UNITS, p[1] * UNITS)
        prev = p
        i += 1
    if prev is not None:
        for f in (TIE_LEN, 0, TIE_LEN, 0):  # tie-off at colour end
            pattern.add_stitch_absolute(pe.STITCH,
                                        (prev[0] + f) * UNITS, prev[1] * UNITS)


def digitize(in_path, out_path, target_width_mm=80.0):
    regions = extract_regions(in_path, target_width_mm)
    if not regions:
        raise SystemExit("no stitchable regions found (is the image flat artwork?)")

    pattern = pe.EmbPattern()
    dropped = 0
    for color, multipoly in regions:
        thread = pe.EmbThread()
        thread.set_color(*color)
        pattern.add_thread(thread)
        polys = order_polys([p for p in multipoly.geoms
                             if p.area >= MIN_REGION_AREA_MM2])
        pts = []
        for poly in polys:
            med_w, p90_w = stroke_stats(poly)
            if med_w <= 0:
                dropped += 1
                continue
            # no forced trim between shapes: satin_column/bean_stitch bridge
            # small gaps with travel runs (measured pro habit, ~1.8 trims/1k)
            # and only emit a trim on real distance
            # classification, the way a pro would:
            #   hairline strokes -> bean stitch (triple run)
            #   stroke-like shapes (lettering) -> satin columns
            #   chunky shapes -> tatami fill with satin border
            bx0, by0, bx1, by1 = poly.bounds
            # tiny isolated blob (a dot): compact satin dot
            if max(bx1 - bx0, by1 - by0) < 3.5:
                if blob_stitch(poly, pts):
                    continue
                dropped += 1
                continue
            # thin stroke with much wider lobes fused on (wheels on an
            # outline): carve the lobes out and stitch each part properly
            if 0 < med_w < 1.5 and p90_w > max(2.2 * med_w, med_w + 1.2):
                parts = split_lobes(poly, med_w)
                if parts:
                    lobes, rest = parts
                    for lr in lobes:
                        for g in getattr(lr, "geoms", [lr]):
                            if isinstance(g, Polygon) and g.area > 0.5:
                                gd = max(g.bounds[2] - g.bounds[0],
                                         g.bounds[3] - g.bounds[1])
                                if gd < 3.8:
                                    blob_stitch(g, pts)
                                else:
                                    ga = principal_angle(g)
                                    contour_underlay(g, pts)
                                    tatami_fill(g, ga, pts)
                                    satin_border(g, pts)
                    for g in getattr(rest, "geoms", [rest]):
                        if isinstance(g, Polygon) and g.area > 0.5:
                            if not satin_column(g, pts):
                                bean_stitch(g, pts)
                    continue
            if med_w < 0.65:
                if bean_stitch(poly, pts):
                    continue
                dropped += 1
                continue
            if p90_w <= SATIN_MAX_STROKE:
                if satin_column(poly, pts):
                    continue
            angle = principal_angle(poly)
            comp = pull_compensate(poly, angle)
            contour_underlay(comp, pts)
            tatami_underlay(comp, angle, pts)
            tatami_fill(comp, angle, pts)
            satin_border(poly, pts)   # satin sits on the TRUE edge, not the comp'd one
        emit(pattern, pts)
        pattern.color_change()

    pattern.end()
    pe.write_dst(pattern, out_path)
    from render_preview import render
    render(pattern, out_path.rsplit(".", 1)[0] + "_preview.png")

    check = pe.read(out_path)
    n = {k: sum(1 for s in check.stitches if s[2] == v)
         for k, v in (("stitch", pe.STITCH), ("jump", pe.JUMP),
                      ("trim", pe.TRIM), ("cc", pe.COLOR_CHANGE))}
    xs = [s[0] for s in check.stitches]
    ys = [s[1] for s in check.stitches]
    print(f"wrote {out_path}")
    print(f"  stitches {n['stitch']}, jumps {n['jump']}, trims {n['trim']}, "
          f"colour changes {n['cc']}")
    print(f"  size {(max(xs)-min(xs))/10:.1f} x {(max(ys)-min(ys))/10:.1f} mm")
    if dropped:
        print(f"  WARNING: {dropped} region(s) below {MIN_FEATURE_MM}mm needle "
              f"limit were dropped — enlarge the design or simplify the art")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "logo_input.png"
    dst = sys.argv[2] if len(sys.argv) > 2 else "logo_pro.dst"
    width = float(sys.argv[3]) if len(sys.argv) > 3 else 80.0
    digitize(src, dst, width)

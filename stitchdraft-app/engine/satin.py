"""
Skeleton-based satin column generation.

Given a polygon that is stroke-like (a letter, a border, a thin shape), this
traces its medial axis, measures the local stroke width along it, and emits
satin zigzag stitches perpendicular to the centre-line — the way a
professional digitizes lettering. Verified against a pro-digitized reference
file ("Sunday's"): satin columns with ~0.4mm density, widths 1.4–7.2mm,
centre-run underlay, sequential branch stitching with travel runs.
"""
import math
import numpy as np
import cv2
from skimage.morphology import medial_axis
from shapely.geometry import Polygon, LineString, Point

RASTER_PX_PER_MM = 8
SATIN_DENSITY = 0.40        # same-side advance, measured from pro file
MIN_SATIN_WIDTH = 0.8       # never throw narrower than this (thread coverage)
MAX_SATIN_WIDTH = 7.5       # pro file maxed at 7.2mm
SPUR_FACTOR = 1.2           # prune skeleton spurs shorter than width*this
RUN_STITCH = 1.9            # underlay/travel run length, from pro file
PULL_COMP = 0.15
MAX_TRAVEL = 1.5            # bridge only near-touching gaps; visible spans get a trim


def travel_or_break(out, next_pt):
    """Bridge to next_pt with travel run stitches when close (pro habit —
    measured ~1.8 trims/1k stitches vs trimming every element), else mark
    a trim+jump with the None sentinel."""
    if not out or out[-1] is None:
        return
    last = out[-1]
    gap = math.hypot(next_pt[0] - last[0], next_pt[1] - last[1])
    if gap <= 1.0:
        return
    if gap <= MAX_TRAVEL:
        n = max(2, int(gap / RUN_STITCH) + 1)
        out.extend((last[0] + (next_pt[0] - last[0]) * t,
                    last[1] + (next_pt[1] - last[1]) * t)
                   for t in np.linspace(0, 1, n)[1:-1])
    else:
        out.append(None)


def _rasterize(poly, px):
    minx, miny, maxx, maxy = poly.bounds
    w = int((maxx - minx) * px) + 8
    h = int((maxy - miny) * px) + 8
    mask = np.zeros((h, w), np.uint8)
    off = np.array([minx - 4 / px, miny - 4 / px])

    def to_px(coords):
        return ((np.array(coords) - off) * px).astype(np.int32)

    cv2.fillPoly(mask, [to_px(poly.exterior.coords)], 1)
    for hole in poly.interiors:
        cv2.fillPoly(mask, [to_px(hole.coords)], 0)
    return mask, off


def _skeleton_paths(mask):
    """Extract ordered pixel paths (branches) from the medial axis.
    Returns (paths, dist, junctions)."""
    skel, dist = medial_axis(mask, return_distance=True)
    ys, xs = np.nonzero(skel)
    pixels = set(zip(ys.tolist(), xs.tolist()))
    if not pixels:
        return [], dist, set()

    def neighbors(p):
        y, x = p
        return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if (dy or dx) and (y + dy, x + dx) in pixels]

    degree = {p: len(neighbors(p)) for p in pixels}
    endpoints = [p for p, d in degree.items() if d == 1]
    junctions = {p for p, d in degree.items() if d >= 3}

    paths = []
    visited_edges = set()

    def walk(start, first):
        path = [start, first]
        visited_edges.add((start, first))
        visited_edges.add((first, start))
        while True:
            cur = path[-1]
            if cur in junctions or degree.get(cur, 0) == 1:
                break
            nxts = [n for n in neighbors(cur) if (cur, n) not in visited_edges]
            if not nxts:
                break
            nxt = nxts[0]
            visited_edges.add((cur, nxt))
            visited_edges.add((nxt, cur))
            path.append(nxt)
        return path

    starts = endpoints + list(junctions)
    for s in starts:
        for n in neighbors(s):
            if (s, n) not in visited_edges:
                p = walk(s, n)
                if len(p) >= 3:
                    paths.append(p)
    # isolated loops (an "O") have no endpoints or junctions
    covered = {p for path in paths for p in path}
    loop_pixels = pixels - covered
    while loop_pixels:
        start = next(iter(loop_pixels))
        n = [x for x in neighbors(start) if x in loop_pixels]
        if not n:
            loop_pixels.discard(start)
            continue
        path = walk(start, n[0])
        if len(path) >= 3:
            paths.append(path)
        loop_pixels -= set(path)
    return paths, dist, junctions


def _order_paths(paths):
    """Greedy nearest-neighbour chaining of branch paths."""
    if not paths:
        return []
    remaining = list(paths)
    ordered = [remaining.pop(0)]
    while remaining:
        tail = np.array(ordered[-1][-1])
        best, flip, bd = None, False, None
        for p in remaining:
            d0 = np.hypot(*(np.array(p[0]) - tail))
            d1 = np.hypot(*(np.array(p[-1]) - tail))
            d = min(d0, d1)
            if bd is None or d < bd:
                bd, best, flip = d, p, d1 < d0
        remaining.remove(best)
        ordered.append(best[::-1] if flip else best)
    return ordered


def satin_column(poly, out, px=RASTER_PX_PER_MM):
    """Emit satin stitches covering a stroke-like polygon.
    Returns False if the shape isn't suitable (caller should fill instead)."""
    mask, off = _rasterize(poly, px)
    paths, dist, junctions = _skeleton_paths(mask)
    if not paths:
        return False

    # prune spurs: branches much shorter than the local stroke width
    kept = []
    for p in paths:
        length_mm = len(p) / px
        w_mm = 2 * np.median([dist[y, x] for y, x in p]) / px
        if length_mm >= max(w_mm * SPUR_FACTOR, 1.0):
            kept.append(p)
    if not kept:
        kept = [max(paths, key=len)]

    # junction easing: branches that terminate at a junction stop short by
    # ~half the local stroke width so the through-branch isn't triple-covered
    # into a knot. The longest branch keeps its full length.
    longest = max(kept, key=len)
    eased = []
    for p in kept:
        q = list(p)
        if p is not longest:
            half_w_px = int(np.median([dist[y, x] for y, x in p]))
            # ease only branches that are long relative to their width —
            # tiny letters' strokes keep their full length
            if len(q) > 3 * half_w_px + 6:
                trim = min(half_w_px, len(q) // 4)
                if trim >= 1:
                    if q[0] in junctions:
                        q = q[trim:]
                    if q[-1] in junctions and len(q) > trim + 3:
                        q = q[:-trim]
        eased.append(q)
    kept = eased

    emitted = False
    for path in _order_paths(kept):
        pts_mm = np.array([(x / px + off[0], y / px + off[1]) for y, x in path])
        # smooth the pixelated skeleton so throw angles don't wobble
        if len(pts_mm) >= 7:
            k = np.ones(5) / 5
            pts_mm[2:-2, 0] = np.convolve(pts_mm[:, 0], k, mode="valid")
            pts_mm[2:-2, 1] = np.convolve(pts_mm[:, 1], k, mode="valid")
        line = LineString(pts_mm)
        if line.length < 0.8:
            continue
        # each sample alternates sides, so sample at density/2 to get the
        # target same-side advance
        n = max(3, int(line.length / (SATIN_DENSITY / 2)))
        samples = [line.interpolate(d) for d in np.linspace(0, line.length, n)]
        coords = [(p.x, p.y) for p in samples]

        # travel/underlay: centre run to the far end and satin back
        travel_or_break(out, coords[0])
        run = LineString(coords)
        rn = max(2, int(run.length / RUN_STITCH))
        out.extend((p.x, p.y) for p in
                   (run.interpolate(d) for d in np.linspace(0, run.length, rn)))

        # satin pass back: tangents over a wide baseline, throws clipped to
        # the letter's true outline for crisp edges
        emitted = True
        side = 1
        REACH = MAX_SATIN_WIDTH  # max half-throw searched
        m = len(coords)
        for k in range(m - 1, -1, -1):
            x, y = coords[k]
            k0, k1 = max(k - 2, 0), min(k + 2, m - 1)
            tx = coords[k1][0] - coords[k0][0]
            ty = coords[k1][1] - coords[k0][1]
            d = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / d, tx / d
            a, b = None, None
            probe = LineString([(x - nx * REACH, y - ny * REACH),
                                (x + nx * REACH, y + ny * REACH)])
            cut = poly.intersection(probe)
            centre = Point(x, y)
            for g in getattr(cut, "geoms", [cut]):
                if isinstance(g, LineString) and g.distance(centre) < 0.3:
                    (ax, ay), (bx, by) = g.coords[0], g.coords[-1]
                    a, b = (ax, ay), (bx, by)
                    break
            if a is None:
                half = MIN_SATIN_WIDTH / 2 + PULL_COMP
                a = (x - nx * half, y - ny * half)
                b = (x + nx * half, y + ny * half)
            else:
                # pull compensation: extend past the true edge
                a = (a[0] - nx * PULL_COMP, a[1] - ny * PULL_COMP)
                b = (b[0] + nx * PULL_COMP, b[1] + ny * PULL_COMP)
                # never throw wider than the cap
                if math.hypot(b[0]-a[0], b[1]-a[1]) > MAX_SATIN_WIDTH:
                    cxm, cym = (a[0]+b[0])/2, (a[1]+b[1])/2
                    a = (cxm - nx * MAX_SATIN_WIDTH/2, cym - ny * MAX_SATIN_WIDTH/2)
                    b = (cxm + nx * MAX_SATIN_WIDTH/2, cym + ny * MAX_SATIN_WIDTH/2)
            out.append(a if side > 0 else b)
            side = -side
    return emitted


def bean_stitch(poly, out, px=RASTER_PX_PER_MM, repeats=3):
    """Triple-run stitch along the skeleton — how pros handle details too
    fine for satin (thin script, hairlines). Each segment is sewn forward,
    back, forward so it reads as a bold line."""
    mask, off = _rasterize(poly, px)
    paths, _, _ = _skeleton_paths(mask)
    if not paths:
        return False
    for path in _order_paths(paths):
        pts_mm = [(x / px + off[0], y / px + off[1]) for y, x in path]
        line = LineString(pts_mm)
        if line.length < 1.0:
            continue
        n = max(2, int(line.length / 1.2))
        pts = [(p.x, p.y) for p in
               (line.interpolate(d) for d in np.linspace(0, line.length, n))]
        travel_or_break(out, pts[0])
        for r in range(repeats):
            seq = pts if r % 2 == 0 else pts[::-1]
            out.extend(seq if r == 0 else seq[1:])
    return True


def blob_stitch(poly, out):
    """Tiny shapes (wheel dots, full stops, eyes) — a compact satin dot:
    a few zigzag throws across the whole shape, the way a pro spots them."""
    minx, miny, maxx, maxy = poly.bounds
    w, h = maxx - minx, maxy - miny
    if max(w, h) < 1.0:
        return False  # truly sub-needle; caller drops it
    cx = (minx + maxx) / 2
    # throw across the taller axis, advancing along the wider one
    n = max(3, int(w / SATIN_DENSITY))
    travel_or_break(out, (minx + 0.2, (miny + maxy) / 2))
    side = 1
    for i in range(n):
        x = minx + (i + .5) * w / n
        # clip throw to the shape at this x
        cut = poly.intersection(LineString([(x, miny - 1), (x, maxy + 1)]))
        if cut.is_empty:
            continue
        lo, hi = cut.bounds[1], cut.bounds[3]
        out.append((x, hi if side > 0 else lo))
        side = -side
    return True


def stroke_stats(poly, px=RASTER_PX_PER_MM):
    """(median_width_mm, p90_width_mm) of a polygon's local stroke widths."""
    mask, off = _rasterize(poly, px)
    skel, dist = medial_axis(mask, return_distance=True)
    ys, xs = np.nonzero(skel)
    if len(ys) == 0:
        return 0.0, 0.0
    w = 2 * dist[ys, xs] / px
    return float(np.median(w)), float(np.percentile(w, 90))

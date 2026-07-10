# Image → Embroidery File (.dst) — Proof of Concept

> **v2:** `digitize_pro.py` is the upgraded engine — see
> [Professional-grade engine](#professional-grade-engine-digitize_propy) below.
> `digitize.py` (v1, fills only) is kept for comparison.

Answers the question: *"Can a PNG/JPG be digitised into a .emb or .dst file?"*

## Short answer

- **.dst (Tajima)** — **yes.** This folder contains a working auto-digitizing
  pipeline that converts a raster logo into a genuine Tajima .dst stitch file
  that any commercial embroidery machine (and Wilcom, Hatch, Ink/Stitch, etc.)
  can open.
- **.emb (Wilcom)** — **no.** .emb is Wilcom's closed proprietary format; there
  is no open-source or third-party library that can write it. The universal
  industry workaround is to output .dst, which Wilcom imports directly.

## What's here

| File | What it is |
|---|---|
| `digitize.py` | The digitizer: PNG/JPG in → .dst out |
| `make_logo.py` | Generates the sample 2-colour badge logo used as input |
| `logo_input.png` | Sample input image |
| `logo.dst` | The generated Tajima embroidery file (1,499 stitch commands, 2 colour changes, ~54 × 45 mm) |
| `logo_stitch_preview.png` | Render of the actual stitches in the .dst |

## How it works

1. **Colour quantization** — the image is reduced to a small thread palette;
   the background colour (detected from the image border) is dropped, and
   antialiasing fringes below a minimum region size are ignored.
2. **Fill stitch generation** — each colour region is filled with serpentine
   scanline (tatami-style) rows at 0.4 mm spacing, with runs split so no
   stitch exceeds 3 mm.
3. **Output** — stitches are written as .dst (native 0.1 mm units) via
   [pyembroidery](https://github.com/EmbroidePy/pyembroidery), one thread
   block per colour with colour-change commands between them.

```bash
pip install pyembroidery pillow numpy
python digitize.py input.png output.dst 80   # 80 = target width in mm
```

## Professional-grade engine (`digitize_pro.py`)

The v2 engine applies the techniques a human digitizer uses, automatically:

- **Vectorization** — OpenCV contour extraction with hole support and
  Douglas-Peucker simplification (works at 1200px internally for clean edges)
- **Underlay** — centre-walk contour underlay inset 0.6 mm from each edge,
  plus sparse perpendicular tatami under large fills to stabilise the fabric
- **Pull compensation** — regions extended 0.2 mm along the stitch direction
  so the design stays true when thread tension pulls the fabric
- **Angled tatami fills** — per-region stitch angle chosen from PCA of the
  shape, with brick-pattern stagger so rows don't ridge
- **Satin borders** — dense zigzag column (1.4 mm, 0.35 mm density) around
  every region edge over an edge-run underlay — the clean raised edge that
  makes embroidery look professional
- **Tie-in / tie-off** — lock stitches at every thread start/stop
- **Stitch routing** — regions sequenced nearest-neighbour per colour to
  minimise jumps and trims
- **Small-detail guard** — details narrower than 1 mm (needle limit) are
  dropped with a warning instead of stitching mush

```bash
pip install pyembroidery pillow numpy opencv-python-headless shapely
python digitize_pro.py input.png output.dst 100   # 100 = width in mm
python vectorize_svg.py input.png output.svg 100  # SVG for Ink/Stitch route
```

Sample results (`logo_text_input.png` → `logo_text.dst`): 5,286 stitches,
2 colour changes, 70 × 58 mm, lettering legible with satin-wrapped edges.
Stitch audit: mean 2.4 mm, max 6.5 mm, zero over-length or micro stitches.

`vectorize_svg.py` also exports the artwork as a millimetre-accurate SVG
(`logo_vector.svg`) so the same vectorization can be loaded into
Inkscape + [Ink/Stitch](https://inkstitch.org/) when you want GUI-tuned
parameters (custom densities per fabric, manual satin direction, etc.).

## Honest limitations vs. professional digitizing

This is auto-digitizing — good for flat, bold, few-colour logo artwork.
It is **not** a replacement for a professional digitizer for production work:

- **No satin stitch / underlay / pull compensation** — fills only. Borders,
  small text and fine detail really want satin columns and underlay, which
  need path-level (vector) information and judgement.
- **Small text fails** — anything under roughly 5 mm letter height turns to
  mush (the sample originally had small "WD" text under the badge and it
  digitized as a blob — that's typical).
- **Photos don't digitize** — the input needs to be logo-style flat artwork,
  not photographic images.
- **.dst carries no colour data** — the format only stores needle movements
  and colour-*change* commands; actual thread colours are assigned at the
  machine or in a colour sheet (this is inherent to .dst, not a limitation
  of this tool).

For higher quality open-source auto-digitizing the usual route is:
raster → vectorize (potrace) → [Ink/Stitch](https://inkstitch.org/) for
satin/fill/underlay stitch planning → .dst. Fully automatic
production-quality digitizing from arbitrary raster images remains an
unsolved problem industry-wide, which is why digitizing services still exist.

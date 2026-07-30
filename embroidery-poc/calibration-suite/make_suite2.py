"""
StitchDraft calibration suite, batch 2 (sheets 11-16): covers what batch 1
didn't — knockout text, script-style lettering, gradients/shading, distress
and halftone texture, tight gaps and counters, and large-area fills.
Same conventions as make_suite.py: 20px = 1mm at 100mm digitize width,
grey text = sheet labels (not stitched).
"""
from PIL import Image, ImageDraw, ImageFont
import math
import random

MM = 20  # px per mm at 100mm digitize width
W = 100 * MM
GREY = (160, 160, 160)
INK = (20, 30, 60)      # navy
ACC = (220, 60, 40)     # red
GOLD = (230, 170, 40)

def font(pt, face="DejaVuSans-Bold.ttf"):
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{face}", pt)

def sheet(h_mm):
    img = Image.new("RGB", (W, int(h_mm * MM)), "white")
    return img, ImageDraw.Draw(img)

def label(d, xy, text):
    d.text(xy, text, font=font(int(2.2 * MM)), fill=GREY)

# ---- 11: knockout (reversed-out) text ---------------------------------------
# White text inside solid fills — the reverse pull-compensation case.
img, d = sheet(64)
y = 3 * MM
for h in [3, 4, 6, 8]:
    band_h = h * MM * 2.1
    d.rounded_rectangle([12 * MM, y, 94 * MM, y + band_h],
                        radius=2 * MM, fill=INK)
    f = font(int(h * MM))
    d.text((53 * MM, y + band_h / 2), "SAFETY FIRST", font=f,
           fill="white", anchor="mm")
    label(d, (1 * MM, y + band_h / 2 - MM), f"{h}mm")
    y += int(band_h) + int(2.5 * MM)
# red band, knockout text + a knockout icon (star)
band_h = 11 * MM
d.rounded_rectangle([12 * MM, y, 94 * MM, y + band_h], radius=2 * MM, fill=ACC)
d.text((58 * MM, y + band_h / 2), "HI-VIS TEAM", font=font(int(5 * MM)),
       fill="white", anchor="mm")
cx, cy = 22 * MM, y + band_h / 2
pts = []
for a in range(10):
    r = (3.5 if a % 2 == 0 else 1.5) * MM
    ang = math.radians(a * 36 - 90)
    pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
d.polygon(pts, fill="white")
img.save("11_knockout_text.png")

# ---- 12: script / slanted connected lettering -------------------------------
# No true script face on this box, so shear serif-bold to a script-like
# oblique, plus a drawn signature flourish (the joined-stroke case).
img, d = sheet(58)
y = 2 * MM
for h in [4, 6, 9, 14]:
    f = font(int(h * MM), "DejaVuSerif-Bold.ttf")
    word = "Quality Stitching" if h <= 6 else "Quality"
    tw = int(d.textlength(word, font=f))
    th = int(h * MM * 1.6)
    txt = Image.new("RGBA", (tw + th, th), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    td.text((th // 2, 0), word, font=f, fill=INK)
    txt = txt.transform(txt.size, Image.AFFINE, (1, -0.3, th * 0.15, 0, 1, 0),
                        resample=Image.BICUBIC)
    img.paste(txt, (13 * MM, y), txt)
    label(d, (1 * MM, y + int(h * MM * 0.3)), f"{h}mm")
    y += th + int(1.5 * MM)
# signature-style flourish: one continuous looping stroke
pts = []
for t in range(0, 100):
    x = 14 * MM + t * 0.78 * MM
    yy = y + 6 * MM + 4 * MM * math.sin(t / 6.0) - 2 * MM * math.sin(t / 17.0)
    pts.append((x, yy))
d.line(pts, fill=ACC, width=int(1.2 * MM), joint="curve")
label(d, (1 * MM, y + 4 * MM), "1.2mm")
img.save("12_script_lettering.png")

# ---- 13: gradients and shading ----------------------------------------------
# Smooth blend, stepped bands, radial shade — the "how do you handle
# photographic art" question, systematically.
img, d = sheet(60)
label(d, (1 * MM, 1 * MM), "smooth")
for i in range(80 * MM):
    t = i / (80 * MM)
    c = tuple(int(INK[k] + (255 - INK[k]) * t) for k in range(3))
    d.line([(10 * MM + i, 4 * MM), (10 * MM + i, 16 * MM)], fill=c)
label(d, (1 * MM, 18 * MM), "5-step")
for s in range(5):
    t = s / 4
    c = tuple(int(INK[k] + (255 - INK[k]) * t * 0.85) for k in range(3))
    d.rectangle([10 * MM + s * 16 * MM, 21 * MM,
                 10 * MM + (s + 1) * 16 * MM, 33 * MM], fill=c)
label(d, (1 * MM, 38 * MM), "radial")
cx, cy, R = 30 * MM, 48 * MM, 10 * MM
for i in range(int(R), 0, -1):
    t = i / R
    c = tuple(int(INK[k] + (255 - INK[k]) * t * 0.9) for k in range(3))
    d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=c)
# two-colour blend bar (red -> gold)
label(d, (48 * MM, 38 * MM), "2-colour")
for i in range(34 * MM):
    t = i / (34 * MM)
    c = tuple(int(ACC[k] + (GOLD[k] - ACC[k]) * t) for k in range(3))
    d.line([(56 * MM + i, 42 * MM), (56 * MM + i, 54 * MM)], fill=c)
img.save("13_gradients.png")

# ---- 14: halftone and distress ----------------------------------------------
rng = random.Random(42)
img, d = sheet(62)
label(d, (1 * MM, 1 * MM), "halftone")
x = 12 * MM
for dia in [0.5, 0.8, 1.2, 1.8, 2.5, 3.5]:
    for row in range(3):
        for col in range(3):
            r = dia * MM / 2
            cx = x + col * (dia + 2) * MM
            cy = 5 * MM + row * (dia + 2) * MM
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=INK)
    label(d, (x, 22 * MM), f"{dia}")
    x += int((dia + 2) * 3 * MM) + 3 * MM
# speckle field
label(d, (1 * MM, 27 * MM), "speckle")
for _ in range(400):
    px = 12 * MM + rng.random() * 76 * MM
    py = 30 * MM + rng.random() * 10 * MM
    r = rng.uniform(0.15, 0.6) * MM
    d.ellipse([px - r, py - r, px + r, py + r], fill=INK)
# distressed rectangle: solid fill with eroded bites and cracks
label(d, (1 * MM, 44 * MM), "distress")
d.rectangle([12 * MM, 46 * MM, 88 * MM, 58 * MM], fill=INK)
for _ in range(120):
    px = 12 * MM + rng.random() * 76 * MM
    py = 46 * MM + rng.random() * 12 * MM
    r = rng.uniform(0.2, 1.4) * MM
    d.ellipse([px - r, py - r, px + r, py + r], fill="white")
for _ in range(10):
    x0 = 12 * MM + rng.random() * 74 * MM
    y0 = 46 * MM + rng.random() * 4 * MM
    pts = [(x0, y0)]
    for _ in range(5):
        pts.append((pts[-1][0] + rng.uniform(-2, 2) * MM,
                    pts[-1][1] + rng.uniform(1, 3) * MM))
    d.line(pts, fill="white", width=int(0.4 * MM))
img.save("14_halftone_distress.png")

# ---- 15: gaps and counters --------------------------------------------------
# How small a white gap between two fills survives; letter counters at size.
img, d = sheet(58)
label(d, (1 * MM, 1 * MM), "gap ladder")
x = 12 * MM
for gap in [0.3, 0.5, 0.8, 1.2, 2.0]:
    d.rectangle([x, 4 * MM, x + 12 * MM, 18 * MM], fill=INK)
    d.rectangle([x + 12 * MM + gap * MM, 4 * MM,
                 x + 24 * MM + gap * MM, 18 * MM], fill=ACC)
    label(d, (x + 8 * MM, 19 * MM), f"{gap}")
    x += int((26 + gap) * MM) + 2 * MM
    if x > 84 * MM:
        break
# second row for remaining gaps
x = 12 * MM
for gap in [1.2, 2.0]:
    d.rectangle([x, 24 * MM, x + 12 * MM, 38 * MM], fill=INK)
    d.rectangle([x + 12 * MM + gap * MM, 24 * MM,
                 x + 24 * MM + gap * MM, 38 * MM], fill=ACC)
    label(d, (x + 8 * MM, 39 * MM), f"{gap}")
    x += int((30 + gap) * MM)
# counters: big glyphs whose holes must survive, + fill with knocked-out star
f = font(int(14 * MM))
d.text((52 * MM, 42 * MM), "O e A", font=f, fill=INK)
d.rectangle([12 * MM, 44 * MM, 40 * MM, 56 * MM], fill=GOLD)
cx, cy = 26 * MM, 50 * MM
pts = []
for a in range(10):
    r = (4.5 if a % 2 == 0 else 2.0) * MM
    ang = math.radians(a * 36 - 90)
    pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
d.polygon(pts, fill="white")
label(d, (42 * MM, 49 * MM), "knockout")
img.save("15_gaps_counters.png")

# ---- 16: large-area fills and direction -------------------------------------
# Jacket-back scale decisions: fill angles, splits, push at size.
img, d = sheet(80)
d.ellipse([8 * MM, 6 * MM, 44 * MM, 42 * MM], fill=INK)          # 36mm disc
d.polygon([(52 * MM, 42 * MM), (72 * MM, 6 * MM), (92 * MM, 42 * MM),
           (84 * MM, 42 * MM), (72 * MM, 20 * MM), (60 * MM, 42 * MM)],
          fill=ACC)                                               # chevron
# sunburst: alternating rays inside a ring
cx, cy = 50 * MM, 62 * MM
d.ellipse([cx - 16 * MM, cy - 16 * MM, cx + 16 * MM, cy + 16 * MM],
          outline=INK, width=int(2 * MM))
for a in range(12):
    ang0 = math.radians(a * 30 - 90)
    ang1 = math.radians(a * 30 - 90 + 15)
    pts = [(cx, cy),
           (cx + 13.5 * MM * math.cos(ang0), cy + 13.5 * MM * math.sin(ang0)),
           (cx + 13.5 * MM * math.cos(ang1), cy + 13.5 * MM * math.sin(ang1))]
    d.polygon(pts, fill=GOLD if a % 2 == 0 else INK)
img.save("16_large_fills.png")

print("suite 2 generated")

"""
StitchDraft calibration suite: 10 test sheets designed so that one pro
digitizing pass over them yields the most informative art->DST pairs
possible. Canvas scale: 20px = 1mm when digitized at 100mm wide.
Grey text = sheet labels, excluded from stitching (see brief).
"""
from PIL import Image, ImageDraw, ImageFont
import math

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

# ---- 1 & 2: lettering ladders (sans + serif) --------------------------------
for name, face in [("01_letter_ladder_sans", "DejaVuSans-Bold.ttf"),
                   ("02_letter_ladder_serif", "DejaVuSerif-Bold.ttf")]:
    img, d = sheet(66)
    y = 2 * MM
    for h in [3, 4, 5, 6, 8, 12]:
        f = font(int(h * MM), face)
        text = "Workwear 2026" if h <= 6 else "Workwear"
        d.text((14 * MM, y), text, font=f, fill=INK)
        label(d, (1 * MM, y + h * MM * 0.15), f"{h}mm")
        y += int(h * MM * 1.45) + MM
    img.save(f"{name}.png")

# ---- 3 & 4: full alphabets (glyph library source) ---------------------------
for name, face in [("03_alphabet_sans", "DejaVuSans-Bold.ttf"),
                   ("04_alphabet_serif_italic", "DejaVuSerif-Bold.ttf")]:
    img, d = sheet(62)
    f = font(int(8 * MM), face)
    rows = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ&123", "4567890.,-"]
    y = 2 * MM
    for row in rows:
        d.text((2 * MM, y), " ".join(row), font=f, fill=INK)
        y += int(13.5 * MM)
    img.save(f"{name}.png")

# ---- 5: stroke-width ladder -------------------------------------------------
img, d = sheet(70)
y = 3 * MM
for wmm in [0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]:
    d.rectangle([10 * MM, y, 90 * MM, y + wmm * MM], fill=INK)
    label(d, (1 * MM, y - MM), f"{wmm}mm")
    y += int(wmm * MM) + int(4.2 * MM)
img.save("05_stroke_ladder.png")

# ---- 6: dots and rings ------------------------------------------------------
img, d = sheet(50)
x = 6 * MM
for dia in [1, 1.5, 2, 3, 4, 6, 8, 10]:
    r = dia * MM / 2
    cy = 10 * MM
    d.ellipse([x - r, cy - r, x + r, cy + r], fill=INK)
    label(d, (x - 2 * MM, 15 * MM), f"{dia}")
    x += int(r * 2) + 5 * MM
x = 8 * MM
for dia, ring in [(4, 0.8), (6, 1.0), (8, 1.5), (10, 2.0), (14, 3.0)]:
    r = dia * MM / 2
    cy = 32 * MM
    d.ellipse([x - r, cy - r, x + r, cy + r], outline=INK, width=int(ring * MM))
    label(d, (x - 3 * MM, 40 * MM), f"{dia}/{ring}")
    x += int(r * 2) + 6 * MM
img.save("06_dots_rings.png")

# ---- 7: junction torture test -----------------------------------------------
img, d = sheet(60)
lw = int(2.5 * MM)
# Y, T, X, +, star
d.line([(10*MM, 25*MM), (16*MM, 10*MM)], fill=INK, width=lw)
d.line([(22*MM, 25*MM), (16*MM, 10*MM)], fill=INK, width=lw)
d.line([(16*MM, 10*MM), (16*MM, 2*MM)], fill=INK, width=lw)
d.line([(30*MM, 3*MM), (46*MM, 3*MM)], fill=INK, width=lw)
d.line([(38*MM, 3*MM), (38*MM, 24*MM)], fill=INK, width=lw)
d.line([(52*MM, 2*MM), (68*MM, 24*MM)], fill=INK, width=lw)
d.line([(68*MM, 2*MM), (52*MM, 24*MM)], fill=INK, width=lw)
cx, cy = 82*MM, 13*MM
for a in range(6):
    ang = a * math.pi / 3
    d.line([(cx, cy), (cx + 11*MM*math.cos(ang), cy + 11*MM*math.sin(ang))],
           fill=INK, width=lw)
# big serif glyphs (the tau case, at friendlier size)
f = font(int(24 * MM), "DejaVuSerif-Bold.ttf")
d.text((8 * MM, 30 * MM), "T K R", font=f, fill=INK)
img.save("07_junctions.png")

# ---- 8: curves and spirals --------------------------------------------------
img, d = sheet(60)
for i, wmm in enumerate([1.0, 2.0, 4.0]):
    x0 = (8 + i * 26) * MM
    pts = [(x0 + 14*MM*math.sin(t/12*math.pi), 4*MM + t * 1.7 * MM)
           for t in range(0, 25)]
    d.line(pts, fill=INK, width=int(wmm * MM), joint="curve")
cx, cy = 84*MM, 26*MM
pts = []
for t in range(0, 720, 6):
    r = (2 + t / 55) * MM
    pts.append((cx + r*math.cos(math.radians(t)), cy + r*math.sin(math.radians(t))))
d.line(pts, fill=ACC, width=int(1.5*MM), joint="curve")
img.save("08_curves.png")

# ---- 9: touching elements (the truck case, systematically) -------------------
img, d = sheet(55)
ow = int(1.2 * MM)
# outline rect with tangent dots below (wheels)
d.rounded_rectangle([6*MM, 6*MM, 34*MM, 20*MM], radius=3*MM, outline=INK, width=ow)
for cx in (12*MM, 27*MM):
    d.ellipse([cx-3*MM, 18*MM, cx+3*MM, 24*MM], fill=INK)
# dot touching a stem (i)
d.rectangle([44*MM, 8*MM, 47*MM, 24*MM], fill=INK)
d.ellipse([43.5*MM, 3*MM, 47.5*MM, 8.2*MM], fill=INK)
# circle tangent to a rule
d.line([(54*MM, 22*MM), (92*MM, 22*MM)], fill=INK, width=int(1.5*MM))
d.ellipse([68*MM, 12*MM, 78*MM, 22.4*MM], fill=INK)
# overlapping rings, two colours (registration + overlap decision)
d.ellipse([8*MM, 32*MM, 26*MM, 50*MM], outline=INK, width=int(2*MM))
d.ellipse([20*MM, 32*MM, 38*MM, 50*MM], outline=ACC, width=int(2*MM))
# fill butted against outline (shared edge)
d.rectangle([54*MM, 32*MM, 74*MM, 48*MM], fill=GOLD)
d.rectangle([54*MM, 32*MM, 74*MM, 48*MM], outline=INK, width=ow)
img.save("09_touching_elements.png")

# ---- 10: composite crest (medium-difficulty acid test) ----------------------
img, d = sheet(80)
# shield
d.polygon([(50*MM, 6*MM), (78*MM, 12*MM), (78*MM, 40*MM), (50*MM, 60*MM),
           (22*MM, 40*MM), (22*MM, 12*MM)], fill=INK)
d.polygon([(50*MM, 10*MM), (74*MM, 15*MM), (74*MM, 38*MM), (50*MM, 55*MM),
           (26*MM, 38*MM), (26*MM, 15*MM)], fill="white")
d.rectangle([26*MM, 15*MM, 74*MM, 26*MM], fill=ACC)
f = font(int(7 * MM))
d.text((50*MM, 20.5*MM), "ACME", font=f, fill="white", anchor="mm")
# quartered lower field
d.rectangle([26*MM, 26*MM, 50*MM, 38*MM], fill=GOLD)
d.polygon([(50*MM, 26*MM), (74*MM, 26*MM), (74*MM, 38*MM), (50*MM, 38*MM)], fill=(60,120,70))
d.polygon([(26*MM, 38*MM), (74*MM, 38*MM), (50*MM, 55*MM)], fill=(90,60,120))
# star + bolt icons
for cx, cy in [(38*MM, 32*MM)]:
    pts = []
    for a in range(10):
        r = (4 if a % 2 == 0 else 1.7) * MM
        ang = math.radians(a * 36 - 90)
        pts.append((cx + r*math.cos(ang), cy + r*math.sin(ang)))
    d.polygon(pts, fill="white")
d.polygon([(60*MM, 28*MM), (64*MM, 28*MM), (61*MM, 32*MM), (65*MM, 32*MM),
           (58*MM, 37*MM), (61*MM, 33*MM), (58*MM, 33*MM)], fill="white")
# banner with small text
d.polygon([(18*MM, 62*MM), (82*MM, 62*MM), (86*MM, 70*MM), (14*MM, 70*MM)], fill=ACC)
f2 = font(int(4.5 * MM))
d.text((50*MM, 66*MM), "EST • QUALITY • 1987", font=f2, fill="white", anchor="mm")
img.save("10_composite_crest.png")

print("suite generated")

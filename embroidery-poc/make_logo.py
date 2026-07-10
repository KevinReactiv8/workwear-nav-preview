"""Create a typical 2-colour workwear-style logo PNG to use as digitizing input."""
from PIL import Image, ImageDraw, ImageFont

W, H = 800, 500
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)

navy = (22, 44, 90)
orange = (235, 110, 30)

# Shield / badge shape
d.polygon([(400, 40), (640, 110), (640, 280), (400, 460), (160, 280), (160, 110)],
          fill=navy)
# Inner chevron
d.polygon([(400, 150), (560, 200), (400, 330), (240, 200)], fill=orange)

# Bold text under badge is typical of workwear branding; keep it big enough to stitch
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
except OSError:
    font = ImageFont.load_default()
# d.text((400, 470), "WD", font=font, fill=navy, anchor="mb")

img.save("logo_input.png")
print("wrote logo_input.png", img.size)

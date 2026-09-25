"""Build a multi-resolution .ico from a sprite frame (used for the exe icon)."""
import glob
import os
import sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
paths = sorted(glob.glob(os.path.join(HERE, "frames", "*.png")))
if not paths:
    sys.exit("No PNG frames found in %s - add your animation there first."
             % os.path.join(HERE, "frames"))

src = Image.open(paths[len(paths) // 2]).convert("RGBA")

# Trim to the real sprite. A plain getbbox() is thrown off by the faint outer
# glow, so threshold the alpha first and then crop that tighter box.
alpha = src.split()[-1]
mask = alpha.point(lambda v: 255 if v > 40 else 0)
bbox = mask.getbbox()
if bbox:
    # Inset slightly so the glow is not clipped hard at the edge.
    pad = 4
    bbox = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(src.width, bbox[2] + pad),
        min(src.height, bbox[3] + pad),
    )
    src = src.crop(bbox)

# Scale to fill the 1024 canvas. NOTE: Image.thumbnail() only ever shrinks,
# so we must compute the target size and use resize() to scale up.
side = 1000
scale = side / max(src.size)
src = src.resize((max(1, round(src.width * scale)),
                  max(1, round(src.height * scale))), Image.LANCZOS)

canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
canvas.alpha_composite(src, ((1024 - src.width) // 2, (1024 - src.height) // 2))

out = os.path.join(HERE, "app.ico")
canvas.save(out, format="ICO", sizes=[(256, 256), (128, 128), (64, 64),
                                      (48, 48), (32, 32), (16, 16)])
print("wrote", out)

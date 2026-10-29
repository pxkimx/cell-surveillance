"""Draw the Cell Surveillance app icon (assets/icon.png, 1024 px)."""
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 2048                      # drawn at twice the size, then reduced
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png")


def rounded_mask(size, box, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def main():
    pad = int(S * 0.098)                                   # macOS icons leave a margin around the tile
    box = (pad, pad, S - pad, S - pad)
    tile = rounded_mask(S, box, int((S - 2 * pad) * 0.225))

    # background: deep blue-black, lighter towards the top left
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) / S
    glow = np.clip(1.0 - np.hypot(xx - 0.30, yy - 0.22) / 0.95, 0, 1) ** 1.6
    bg = np.zeros((S, S, 3), np.float32)
    bg[..., 0] = 8 + 22 * glow
    bg[..., 1] = 12 + 34 * glow
    bg[..., 2] = 22 + 58 * glow
    img = Image.fromarray(bg.clip(0, 255).astype(np.uint8)).convert("RGBA")

    cx, cy = int(S * 0.545), int(S * 0.535)
    a, b, tilt = int(S * 0.205), int(S * 0.160), -24        # the nucleus

    def ellipse_layer(ax, bx, fill=None, outline=None, width=0, blur=0):
        layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        e = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(e).ellipse((cx - ax, cy - bx, cx + ax, cy + bx), fill=fill, outline=outline, width=width)
        e = e.rotate(tilt, center=(cx, cy), resample=Image.BICUBIC)
        if blur:
            e = e.filter(ImageFilter.GaussianBlur(blur))
        layer.alpha_composite(e)
        return layer

    # reporter leaking into the cytoplasm, then the nucleus itself
    img.alpha_composite(ellipse_layer(int(a * 1.75), int(b * 1.85), fill=(60, 230, 120, 70), blur=S * 0.045))
    img.alpha_composite(ellipse_layer(int(a * 1.05), int(b * 1.05), fill=(70, 255, 140, 150), blur=S * 0.02))
    img.alpha_composite(ellipse_layer(a, b, fill=(88, 240, 130, 255)))
    img.alpha_composite(ellipse_layer(int(a * 0.62), int(b * 0.55), fill=(190, 255, 205, 120), blur=S * 0.03))
    img.alpha_composite(ellipse_layer(a + int(S * 0.030), b + int(S * 0.030), outline=(90, 200, 255, 255),
                                      width=int(S * 0.016)))

    d = ImageDraw.Draw(img)
    # the track: where the cell has been
    pts = []
    for i in range(7):
        t = i / 6
        x = S * (0.205 + 0.20 * t) + S * 0.018 * math.sin(t * 5.0)
        y = S * (0.800 - 0.150 * t) - S * 0.045 * math.sin(t * 3.1)
        pts.append((x, y))
    d.line(pts, fill=(90, 200, 255, 150), width=int(S * 0.010), joint="curve")
    for i, (x, y) in enumerate(pts):
        r = S * (0.011 + 0.0025 * i)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(90, 200, 255, 110 + 22 * i))

    # the rupture: a bright break on the nuclear envelope
    ang = math.radians(-38)
    ex, ey = (a + S * 0.030) * math.cos(ang), (b + S * 0.030) * math.sin(ang)
    rot = math.radians(-tilt)
    rx = cx + ex * math.cos(rot) + ey * math.sin(rot)
    ry = cy - ex * math.sin(rot) + ey * math.cos(rot)
    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hr = S * 0.085
    ImageDraw.Draw(halo).ellipse((rx - hr, ry - hr, rx + hr, ry + hr), fill=(255, 64, 129, 150))
    img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(S * 0.028)))
    d = ImageDraw.Draw(img)
    r = S * 0.046
    d.ellipse((rx - r, ry - r, rx + r, ry + r), fill=(255, 64, 129, 255), outline=(255, 255, 255, 235),
              width=int(S * 0.009))

    # viewfinder corners: the cell is being watched
    inset, arm, w = int(S * 0.175), int(S * 0.095), int(S * 0.017)
    white = (255, 255, 255, 235)
    for sx, sy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        x = inset if sx == 0 else S - inset
        y = inset if sy == 0 else S - inset
        dx = arm if sx == 0 else -arm
        dy = arm if sy == 0 else -arm
        d.line([(x, y + dy), (x, y), (x + dx, y)], fill=white, width=w, joint="curve")
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=white)
        for px, py in ((x, y + dy), (x + dx, y)):
            d.ellipse((px - w / 2, py - w / 2, px + w / 2, py + w / 2), fill=white)

    # soft highlight along the top edge, then cut to the tile shape with a shadow underneath
    sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rounded_rectangle(box, radius=int((S - 2 * pad) * 0.225), outline=(255, 255, 255, 46),
                                            width=int(S * 0.006))
    img.alpha_composite(sheen)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 120), (0, int(S * 0.012)), tile)
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S * 0.014)))
    out.paste(img, (0, 0), tile)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.resize((1024, 1024), Image.LANCZOS).save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()

"""Generate the app icon (spotderpy/assets/icon.ico + icon.png). Run: python scripts/make_icon.py

Deliberately avoids Spotify/YouTube logos and brand colors.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "spotderpy" / "assets"
TOP_LEFT = (124, 58, 237)  # violet
BOTTOM_RIGHT = (251, 113, 133)  # coral
S = 1024  # draw big, downsample for crisp edges


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP_LEFT, BOTTOM_RIGHT))
    return img


def render(with_waves: bool) -> Image.Image:
    bg = gradient(256).resize((S, S), Image.BICUBIC)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, S - 32, S - 32), radius=230, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    if with_waves:
        # play triangle on the left, two "sound" arcs on the right
        tri = [(250, 300), (250, 724), (590, 512)]
        d.polygon(tri, fill=white)
        for r, w in ((150, 54), (270, 54)):
            box = (560 - r, 512 - r, 560 + r, 512 + r)
            d.arc(box, start=-48, end=48, fill=white, width=w)
    else:
        # small sizes: just a bold, centered play triangle
        d.polygon([(370, 270), (370, 754), (774, 512)], fill=white)
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = render(with_waves=True)
    small = render(with_waves=False)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [(small if s <= 32 else big).resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    big.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    small.resize((64, 64), Image.LANCZOS).save(ASSETS / "tray.png")
    print("wrote", *(p.name for p in ASSETS.iterdir()))


if __name__ == "__main__":
    main()

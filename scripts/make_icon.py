"""web/public/pwa-512x512.png -> a Windows .ico for the desktop/Start menu shortcuts.

Written by hand instead of Pillow's ICO writer, to get the layout Windows
expects everywhere (Explorer, Start search, taskbar): 32-bit RGBA images,
bitmaps for 16-128 px and a PNG for 256 px. The source PNG is palette-based,
which Windows can't show inside an .ico (a blank page appears instead).

    python scripts/make_icon.py <out.ico>
"""
import io
import struct
import sys
from pathlib import Path

from PIL import Image

SOURCE = Path(__file__).resolve().parents[1] / "web" / "public" / "pwa-512x512.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def bitmap(img: Image.Image) -> bytes:
    """One icon image as a 32-bit BMP (BITMAPINFOHEADER + BGRA rows bottom-up + AND mask)."""
    w, h = img.size
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = img.getpixel((x, y))
            pixels += bytes((b, g, r, a))
    mask_row = ((w + 31) // 32) * 4  # all zero: alpha decides
    return header + bytes(pixels) + bytes(mask_row * h)


def main(out: str) -> None:
    src = Image.open(SOURCE).convert("RGBA")
    images = []
    for size in SIZES:
        img = src.resize((size, size), Image.LANCZOS)
        if size == 256:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            images.append((size, buf.getvalue()))
        else:
            images.append((size, bitmap(img)))
    data = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, blob in images:
        dim = 0 if size == 256 else size  # 0 means 256
        data += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    data += b"".join(blob for _, blob in images)
    Path(out).write_bytes(data)


if __name__ == "__main__":
    main(sys.argv[1])

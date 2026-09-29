"""Regenerate the attachment fixtures (ADR 0008).

Run from frontend/: `uv run --project ../backend python e2e/fixtures/make_fixtures.py`.

The fake models don't look at the content, so the files only need to be valid.
"""

import wave
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent


def worksheet(size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(size[1] // 6, size[1], size[1] // 6):
        draw.line([(size[0] // 10, y), (size[0] * 9 // 10, y)], fill="navy", width=3)
    return image


worksheet((400, 300)).save(HERE / "worksheet.png")
# Larger than the 1600px the frontend scales down to.
worksheet((3000, 2000)).save(HERE / "big-photo.png")
# A page that is only a picture, no text layer: the backend treats it as scanned.
worksheet((850, 1100)).save(HERE / "scanned.pdf", resolution=100)

with wave.open(str(HERE / "voice.wav"), "wb") as audio:
    audio.setnchannels(1)
    audio.setsampwidth(2)
    audio.setframerate(8000)
    audio.writeframes(b"\x00\x00" * 8000)  # one second of silence

(HERE / "essay.txt").write_text("My weekend: I goed to the park and eated ice cream.\n")

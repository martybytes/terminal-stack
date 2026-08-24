"""Prepare production web assets from approved fal.ai image generations.

This script performs deterministic cleanup and resizing only. It does not call
fal.ai and never reads an API key.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


TURQUOISE = (83, 226, 221)
PERIWINKLE = (138, 128, 240)
MIDNIGHT = (0, 7, 45)


def lerp(start: int, end: int, amount: float) -> int:
    return round(start + (end - start) * amount)


def extract_logo(source: Path) -> Image.Image:
    """Remove the generated backing tile and apply the product palette."""

    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    recolored = Image.new("RGBA", image.size)
    output = recolored.load()
    width, height = image.size

    for y in range(height):
        for x in range(width):
            red, green, blue, source_alpha = pixels[x, y]

            # The approved generation uses a green mark on a navy tile. Green
            # minus blue separates the mark cleanly while retaining soft edges.
            edge_alpha = round(max(0, min(255, (green - blue + 38) * 255 / 118)))
            alpha = round(edge_alpha * source_alpha / 255)
            if alpha == 0:
                continue

            mix = max(0.0, min(1.0, (x / width) * 0.7 + (y / height) * 0.3))
            output[x, y] = (
                lerp(TURQUOISE[0], PERIWINKLE[0], mix),
                lerp(TURQUOISE[1], PERIWINKLE[1], mix),
                lerp(TURQUOISE[2], PERIWINKLE[2], mix),
                alpha,
            )

    bounds = recolored.getchannel("A").getbbox()
    if bounds is None:
        raise RuntimeError("No logo foreground was found in the source image")

    mark = recolored.crop(bounds)
    master = Image.new("RGBA", (1024, 1024))
    mark.thumbnail((820, 820), Image.Resampling.LANCZOS)
    master.alpha_composite(mark, ((1024 - mark.width) // 2, (1024 - mark.height) // 2))
    return master


def rounded_icon(mark: Image.Image, size: int) -> Image.Image:
    icon = Image.new("RGBA", (size, size))
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=round(size * 0.22), fill=255
    )
    backing = Image.new("RGBA", (size, size), (*MIDNIGHT, 255))
    icon.paste(backing, mask=mask)

    inset = round(size * 0.13)
    scaled = mark.resize((size - inset * 2, size - inset * 2), Image.Resampling.LANCZOS)
    icon.alpha_composite(scaled, (inset, inset))
    return icon


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logo-source", type=Path, required=True)
    parser.add_argument("--background-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    mark = extract_logo(args.logo_source)
    mark.save(args.output / "agent007memory-mark.png", optimize=True)

    for size in (16, 32):
        mark.resize((size, size), Image.Resampling.LANCZOS).save(
            args.output / f"favicon-{size}.png", optimize=True
        )

    apple_icon = rounded_icon(mark, 180)
    apple_icon.save(args.output / "apple-touch-icon.png", optimize=True)

    ico_source = rounded_icon(mark, 256)
    ico_source.save(
        args.output.parent / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64)],
    )

    background = Image.open(args.background_source).convert("RGB")
    background.save(
        args.output / "agent007memory-empty-state.webp",
        format="WEBP",
        quality=88,
        method=6,
    )


if __name__ == "__main__":
    main()

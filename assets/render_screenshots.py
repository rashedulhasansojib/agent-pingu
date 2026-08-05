#!/usr/bin/env python3
"""Render the README's terminal screenshots from captured command output.

The images are generated rather than photographed so they can be regenerated
when the output changes — a screenshot of a CLI is documentation, and this repo
holds documentation to the same standard as code. `transcripts/` holds the real
captured output; nothing here invents a line.

    python3 assets/render_screenshots.py

Needs Pillow, which is a tooling dependency of this script only — not of the
plugin, and not of its test suite.
"""

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
TRANSCRIPTS = HERE / "transcripts"

SCALE = 2                      # render at 2x so the PNG stays crisp when scaled
FONT_SIZE = 15 * SCALE
LINE_HEIGHT = 23 * SCALE
PAD = 22 * SCALE
TITLEBAR = 34 * SCALE
RADIUS = 10 * SCALE

BG = (22, 24, 29)
TITLEBAR_BG = (32, 35, 42)
FG = (205, 211, 222)
DIM = (122, 132, 148)
PROMPT = (126, 191, 255)
GREEN = (126, 209, 138)
YELLOW = (226, 192, 106)
RED = (238, 129, 128)
WHITE = (238, 242, 248)

FONTS = ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf")


def load_font():
    for path in FONTS:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except OSError:
            continue
    raise SystemExit("no monospace font found; edit FONTS for your platform")


def colour_for(line):
    """One colour per line, chosen by what the tooling actually prints.

    Deliberately coarse. A screenshot's job is to make the shape of the output
    legible at a glance, not to reproduce a terminal emulator.
    """
    stripped = line.strip()
    if stripped.startswith("$"):
        return PROMPT
    if stripped.startswith("passed") or "no problems found" in stripped:
        return GREEN
    if stripped.startswith(("manual-review", "planned", "not-declared")):
        return YELLOW
    if stripped.startswith("failed") or "problem(s)" in stripped:
        return RED
    if "SETUP NEEDED" in stripped or "outstanding" in stripped:
        return YELLOW
    if stripped.startswith("duplicate id") or " unknown status " in stripped:
        return RED
    if stripped.startswith(("broken link", "T-", "epic ")) and ":" in stripped:
        return RED
    if stripped.startswith("[pingu]") or stripped.startswith("[gate]"):
        return FG
    if not stripped:
        return FG
    return DIM


def render(name, title):
    lines = (TRANSCRIPTS / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n").split("\n")
    font = load_font()

    # Measure the widest line as drawn rather than multiplying a character
    # advance: the glyph advance under-counts what the anti-aliased text
    # actually occupies, and the longest line ended up touching the frame.
    widest = max(font.getlength(l) for l in lines)
    img_w = int(widest) + PAD * 2 + FONT_SIZE
    img_h = TITLEBAR + PAD + LINE_HEIGHT * len(lines) + PAD

    image = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([0, 0, img_w - 1, img_h - 1], radius=RADIUS, fill=BG)
    draw.rounded_rectangle([0, 0, img_w - 1, TITLEBAR + RADIUS], radius=RADIUS, fill=TITLEBAR_BG)
    draw.rectangle([0, TITLEBAR - 1, img_w, TITLEBAR + 1], fill=TITLEBAR_BG)

    for i, colour in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        cx = PAD + i * 20 * SCALE
        cy = TITLEBAR // 2
        r = 6 * SCALE
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    label_font = ImageFont.truetype(FONTS[0], 12 * SCALE)
    draw.text((img_w // 2, TITLEBAR // 2), title, font=label_font,
              fill=DIM, anchor="mm")

    y = TITLEBAR + PAD
    for line in lines:
        draw.text((PAD, y), line, font=font, fill=colour_for(line))
        y += LINE_HEIGHT

    out = HERE / f"{name}.png"
    image.save(out, optimize=True)
    print(f"{out.relative_to(HERE.parent)}  {img_w // SCALE}x{img_h // SCALE}")


SHOTS = {
    "onboard": "agent-pingu — a new repo",
    "gate": "agent-pingu — the verify gate",
    "doctor": "agent-pingu — vault validation",
}

if __name__ == "__main__":
    missing = [n for n in SHOTS if not (TRANSCRIPTS / f"{n}.txt").is_file()]
    if missing:
        sys.exit(f"missing transcripts: {', '.join(missing)}")
    for name, title in SHOTS.items():
        render(name, title)

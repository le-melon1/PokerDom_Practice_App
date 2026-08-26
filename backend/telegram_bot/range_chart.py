"""Renders a standard 13x13 poker hand-range grid (pairs on the diagonal,
suited combos above it, offsuit below) as a PNG, for Telegram's send_photo.
One color for hands in the given range, another for hands not in it --
exactly the "квадрат со всеми руками и одним цветом какие играем, какие
нет" the user asked for."""

import io

from PIL import Image, ImageDraw, ImageFont

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]

CELL = 44
MARGIN = 6
LABEL = 22
WIDTH = HEIGHT = MARGIN * 2 + LABEL + CELL * 13

COLOR_IN = (74, 158, 92)  # confirmed-positive green, matches the "play this" read
COLOR_OUT = (231, 235, 240)  # neutral grey -- "don't play"
COLOR_BORDER = (200, 205, 210)
COLOR_TEXT_IN = (255, 255, 255)
COLOR_TEXT_OUT = (110, 118, 126)
COLOR_LABEL = (90, 98, 106)
COLOR_BG = (255, 255, 255)


def _notation(row: int, col: int) -> str:
    r1, r2 = RANKS[row], RANKS[col]
    if row == col:
        return r1 + r2
    if row < col:
        return r1 + r2 + "s"
    return r2 + r1 + "o"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_range_chart(hand_set: set[str], title: str = "") -> bytes:
    """hand_set: notations like {"AA","AKs","AKo","76s"}. Returns PNG bytes."""
    img = Image.new("RGB", (WIDTH, HEIGHT + (30 if title else 0)), COLOR_BG)
    draw = ImageDraw.Draw(img)
    font_cell = _font(13)
    font_label = _font(14)
    font_title = _font(16)

    y_offset = 0
    if title:
        draw.text((MARGIN, 6), title, fill=(30, 34, 38), font=font_title)
        y_offset = 30

    origin_x = MARGIN + LABEL
    origin_y = MARGIN + LABEL + y_offset

    for i, rank in enumerate(RANKS):
        cx = origin_x + i * CELL + CELL // 2
        draw.text((cx, MARGIN + y_offset + LABEL // 2), rank, fill=COLOR_LABEL, font=font_label, anchor="mm")
        cy = origin_y + i * CELL + CELL // 2
        draw.text((MARGIN + LABEL // 2, cy), rank, fill=COLOR_LABEL, font=font_label, anchor="mm")

    for row in range(13):
        for col in range(13):
            notation = _notation(row, col)
            in_range = notation in hand_set
            x0 = origin_x + col * CELL
            y0 = origin_y + row * CELL
            x1, y1 = x0 + CELL, y0 + CELL
            fill = COLOR_IN if in_range else COLOR_OUT
            draw.rectangle([x0, y0, x1, y1], fill=fill, outline=COLOR_BORDER)
            text_color = COLOR_TEXT_IN if in_range else COLOR_TEXT_OUT
            draw.text(((x0 + x1) // 2, (y0 + y1) // 2), notation, fill=text_color, font=font_cell, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

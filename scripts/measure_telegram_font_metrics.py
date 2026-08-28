"""Measures real glyph advance widths for the fonts Telegram Android
actually renders with (Roboto for text, NotoColorEmoji for emoji fallback),
to compute exact padding for backend/telegram_bot/formatting.py's table
view -- per user request ("посмотри специфику... узнай какой шрифт и
посчитай нормально") after many rounds of guessing space counts blind.

Whole-space rounding alone still left up to ~0.12em of residual error per
name/position/stack ("карлу как будто не помешал бы ещё один пробел" --
a real, visible gap between just two names). This version searches
combinations of a regular space (0.2476em) and a U+200A HAIR SPACE
(0.1021em, a much finer Unicode space that exists in Roboto) to close
that gap much tighter (max residual error under ~0.022em).

Downloads both real font files and measures with fontTools. Run this
again (and copy the resulting BOT_NAME_PAD/POSITION_PAD/STACK_PAD dicts
into formatting.py) if the bot name pool, position labels, or font choice
ever change.

Usage: .venv/bin/python3 scripts/measure_telegram_font_metrics.py
"""

import subprocess
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont

ROBOTO_URL = "https://github.com/googlefonts/roboto-2/raw/main/src/hinted/Roboto-Regular.ttf"
NOTO_EMOJI_URL = "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf"

EMOJI_CODEPOINTS = {
    "🔘": 0x1F518,
    "👉": 0x1F449,
    "🎯": 0x1F3AF,
    "🔒": 0x1F512,
    "🐟": 0x1F41F,
    "📞": 0x1F4DE,
    "🤪": 0x1F92A,
    "⚡": 0x26A1,
    "❄": 0x2744,
    "☁": 0x2601,
    "🔥": 0x1F525,
    "⬆": 0x2B06,
}

BOT_NAMES = ["Bob", "Den", "Carl", "Max", "Leo", "Sam", "Tom", "Jack", "Alex", "Ivan", "You"]
STACK_REFERENCE_INT_DIGITS = 4  # e.g. "9999.9" -- the widest stack this pads up to
POSITIONS = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
HAIR_CODEPOINT = 0x200A


def _download(url: str, dest: Path) -> None:
    subprocess.run(["curl", "-sL", "-o", str(dest), url, "--max-time", "60"], check=True)


def _best_combo(deficit: float, space: float, hair: float, max_spaces: int = 12, max_hairs: int = 8) -> tuple[float, int, int]:
    """(error, n_spaces, n_hairs) minimizing |n_spaces*space + n_hairs*hair - deficit|."""
    best = None
    for a in range(max_spaces + 1):
        for b in range(max_hairs + 1):
            err = abs(a * space + b * hair - deficit)
            if best is None or err < best[0]:
                best = (err, a, b)
    return best


def _pad_repr(n_spaces: int, n_hairs: int) -> str:
    parts = []
    if n_spaces:
        parts.append(f'" " * {n_spaces}')
    if n_hairs:
        parts.append(f"_HAIR * {n_hairs}")
    return " + ".join(parts) if parts else '""'


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    roboto_path = tmp / "Roboto.ttf"
    emoji_path = tmp / "NotoColorEmoji.ttf"
    _download(ROBOTO_URL, roboto_path)
    _download(NOTO_EMOJI_URL, emoji_path)

    roboto = TTFont(roboto_path)
    upem_r = roboto["head"].unitsPerEm
    hmtx_r = roboto["hmtx"]
    cmap_r = roboto.getBestCmap()

    def rw(cp: int) -> float:
        gname = cmap_r[cp]
        adv, _lsb = hmtx_r[gname]
        return adv / upem_r

    def rws(ch: str) -> float:
        return rw(ord(ch))

    emoji_font = TTFont(emoji_path, fontNumber=0, lazy=True)
    upem_e = emoji_font["head"].unitsPerEm
    hmtx_e = emoji_font["hmtx"]
    cmap_e = emoji_font.getBestCmap()

    def ew(cp: int) -> float:
        gname = cmap_e[cp]
        adv, _lsb = hmtx_e[gname]
        return adv / upem_e

    space = rws(" ")
    hair = rw(HAIR_CODEPOINT)
    emoji_widths = {label: ew(cp) for label, cp in EMOJI_CODEPOINTS.items()}
    assert len(set(round(w, 6) for w in emoji_widths.values())) == 1, "expected all emoji to share one width"
    emoji_width = next(iter(emoji_widths.values()))

    print(f"space width: {space:.4f} em")
    print(f"hair space width: {hair:.4f} em")
    print(f"emoji width: {emoji_width:.4f} em ({emoji_width / space:.2f} spaces)")
    digit_widths = {d: rws(d) for d in "0123456789"}
    assert len(set(round(w, 6) for w in digit_widths.values())) == 1, "expected digits to be tabular"
    print(f"digit width: {next(iter(digit_widths.values())):.4f} em (confirmed tabular)")
    print()

    name_target = max(sum(rws(c) for c in n) for n in BOT_NAMES) + space
    print("BOT_NAME_PAD = {")
    for n in BOT_NAMES:
        raw = sum(rws(c) for c in n)
        err, a, b = _best_combo(name_target - raw, space, hair)
        print(f'    "{n}": {_pad_repr(a, b)},  # err={err:.4f}em')
    print("}")
    print()

    position_target = emoji_width * 2 + space  # hero's slot replaces archetype+sep+freq_tier
    print("POSITION_PAD = {")
    for label in POSITIONS:
        raw = sum(rws(c) for c in label)
        err, a, b = _best_combo(position_target - raw, space, hair)
        print(f'    "{label}": {_pad_repr(a, b)},  # err={err:.4f}em')
    print("}")
    print()

    # Stack numbers are always "<int digits>.<1 decimal digit>".
    digit = rws("0")
    period = rws(".")
    reference_width = (STACK_REFERENCE_INT_DIGITS + 1) * digit + period
    print("STACK_PAD = {")
    for n_int_digits in range(1, STACK_REFERENCE_INT_DIGITS + 1):
        text_width = (n_int_digits + 1) * digit + period
        err, a, b = _best_combo(reference_width - text_width, space, hair)
        print(f"    {n_int_digits}: {_pad_repr(a, b)},  # err={err:.4f}em")
    print("}")


if __name__ == "__main__":
    main()

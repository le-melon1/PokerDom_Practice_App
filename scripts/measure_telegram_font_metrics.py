"""Measures real glyph advance widths for the fonts Telegram Android
actually renders with (Roboto for text, NotoColorEmoji for emoji fallback),
to compute exact space-padding for backend/telegram_bot/formatting.py's
table view -- per user request ("посмотри специфику... узнай какой шрифт
и посчитай нормально") after many rounds of guessing space counts blind.

Downloads both real font files and measures with fontTools. Run this
again (and copy the resulting BOT_NAME_TRAILING_SPACES/
POSITION_TRAILING_SPACES dicts into formatting.py) if the bot name pool,
position labels, or font choice ever change.

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

BOT_NAMES = ["Bob", "Den", "Carl", "Max", "Leo", "Sam", "Tom", "Jack", "Alex", "Ivan", "Вы"]
POSITIONS = ["UTG", "MP", "CO", "BTN", "SB", "BB"]


def _download(url: str, dest: Path) -> None:
    subprocess.run(["curl", "-sL", "-o", str(dest), url, "--max-time", "60"], check=True)


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

    def rw(ch: str) -> float:
        gname = cmap_r[ord(ch)]
        adv, _lsb = hmtx_r[gname]
        return adv / upem_r

    emoji_font = TTFont(emoji_path, fontNumber=0, lazy=True)
    upem_e = emoji_font["head"].unitsPerEm
    hmtx_e = emoji_font["hmtx"]
    cmap_e = emoji_font.getBestCmap()

    def ew(cp: int) -> float:
        gname = cmap_e[cp]
        adv, _lsb = hmtx_e[gname]
        return adv / upem_e

    space = rw(" ")
    emoji_widths = {label: ew(cp) for label, cp in EMOJI_CODEPOINTS.items()}
    assert len(set(round(w, 6) for w in emoji_widths.values())) == 1, "expected all emoji to share one width"
    emoji_width = next(iter(emoji_widths.values()))

    print(f"space width: {space:.4f} em")
    print(f"emoji width: {emoji_width:.4f} em ({emoji_width / space:.2f} spaces)")
    digit_widths = {d: rw(d) for d in "0123456789"}
    assert len(set(round(w, 6) for w in digit_widths.values())) == 1, "expected digits to be tabular"
    print(f"digit width: {next(iter(digit_widths.values())):.4f} em (confirmed tabular)")
    print()

    name_target = max(sum(rw(c) for c in n) for n in BOT_NAMES) + space
    print("BOT_NAME_TRAILING_SPACES = {")
    for n in BOT_NAMES:
        raw = sum(rw(c) for c in n)
        spaces = round((name_target - raw) / space)
        print(f'    "{n}": {spaces},')
    print("}")
    print()

    position_target = emoji_width * 2 + space  # hero's slot replaces archetype+sep+freq_tier
    print("POSITION_TRAILING_SPACES = {")
    for label in POSITIONS:
        raw = sum(rw(c) for c in label)
        spaces = round((position_target - raw) / space)
        print(f'    "{label}": {spaces},')
    print("}")


if __name__ == "__main__":
    main()

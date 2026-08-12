#!/usr/bin/env python3
"""Summarize paired common-random A/B output from simulate_abc_bot.py logs."""

import re
import sys
from pathlib import Path

RESULT_RE = re.compile(r"^(?P<label>.+?) delta: (?P<delta>[+-]\d+\.\d+) bb/100$")
PAIRED_RE = re.compile(
    r"^(?P<label>.+?) paired delta: (?P<delta>[+-]\d+\.\d+) bb/100 "
    r"\(95% CI \+/- (?P<ci>\d+\.\d+), paired non-monster hands: (?P<n>\d+)\)$"
)
SHRINK_RE = re.compile(
    r"^(?P<label>.+?) CI shrink: independent \+/- (?P<ind>\d+\.\d+) -> "
    r"paired \+/- (?P<paired>\d+\.\d+) \((?P<ratio>\d+\.\d+)x tighter\)$"
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: scripts/summarize_common_random_log.py /tmp/common_random_confirm_*.log")

    log_path = Path(sys.argv[1])
    current_delta: dict[str, float] = {}
    paired: dict[str, dict[str, float | int]] = {}
    shrink: dict[str, dict[str, float]] = {}

    for line in log_path.read_text().splitlines():
        if match := RESULT_RE.match(line):
            current_delta[match.group("label")] = float(match.group("delta"))
        elif match := PAIRED_RE.match(line):
            paired[match.group("label")] = {
                "paired_delta": float(match.group("delta")),
                "paired_ci": float(match.group("ci")),
                "paired_n": int(match.group("n")),
            }
        elif match := SHRINK_RE.match(line):
            shrink[match.group("label")] = {
                "independent_ci": float(match.group("ind")),
                "ci_shrink": float(match.group("ratio")),
            }

    labels = sorted(paired)
    if not labels:
        raise SystemExit(f"no paired results found in {log_path}")

    print("label,delta,paired_delta,paired_ci,paired_low,paired_high,independent_ci,ci_shrink,paired_n")
    for label in labels:
        p = paired[label]
        s = shrink.get(label, {})
        paired_delta = float(p["paired_delta"])
        paired_ci = float(p["paired_ci"])
        print(
            f"{label},"
            f"{current_delta.get(label, '')},"
            f"{paired_delta:.2f},"
            f"{paired_ci:.2f},"
            f"{paired_delta - paired_ci:.2f},"
            f"{paired_delta + paired_ci:.2f},"
            f"{s.get('independent_ci', '')},"
            f"{s.get('ci_shrink', '')},"
            f"{p['paired_n']}"
        )


if __name__ == "__main__":
    main()

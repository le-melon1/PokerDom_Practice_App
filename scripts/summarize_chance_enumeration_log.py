#!/usr/bin/env python3
"""Summarize scripts/probe_chance_enumeration.py batch logs as CSV."""

import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^(?P<label>.+?) \((?P<preset>v\d+[a-z0-9-]*)\)$")
HANDS_RE = re.compile(r"^hands: (?P<hands>\d+), divergent hero hands: (?P<div>\d+) \((?P<rate>\d+\.\d+)%\)$")
BRANCH_RE = re.compile(r"^avg next-card branches when divergent: (?P<branches>\d+\.\d+)$")
RANDOM_RE = re.compile(r"^random continuation delta: (?P<delta>[+-]\d+\.\d+) bb/100 \(95% CI \+/- (?P<ci>\d+\.\d+)\)$")
ENUM_RE = re.compile(r"^next-card enumerated delta: (?P<delta>[+-]\d+\.\d+) bb/100 \(95% CI \+/- (?P<ci>\d+\.\d+)\)$")
SHRINK_RE = re.compile(r"^CI shrink from enumeration: (?P<shrink>\d+\.\d+|inf)x$")
ELAPSED_RE = re.compile(r"^elapsed: (?P<elapsed>\d+\.\d+)s$")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: scripts/summarize_chance_enumeration_log.py /tmp/chance_enumeration_confirm_*.log")

    rows = []
    current = None
    for line in Path(sys.argv[1]).read_text().splitlines():
        if match := HEADER_RE.match(line):
            if current:
                rows.append(current)
            current = {"label": match.group("label"), "preset": match.group("preset")}
        elif current and (match := HANDS_RE.match(line)):
            current.update({"hands": match.group("hands"), "divergent": match.group("div"), "divergent_rate": match.group("rate")})
        elif current and (match := BRANCH_RE.match(line)):
            current["avg_branches"] = match.group("branches")
        elif current and (match := RANDOM_RE.match(line)):
            current.update({"random_delta": match.group("delta"), "random_ci": match.group("ci")})
        elif current and (match := ENUM_RE.match(line)):
            delta = float(match.group("delta"))
            ci = float(match.group("ci"))
            current.update({
                "enum_delta": f"{delta:.2f}",
                "enum_ci": f"{ci:.2f}",
                "enum_low": f"{delta - ci:.2f}",
                "enum_high": f"{delta + ci:.2f}",
            })
        elif current and (match := SHRINK_RE.match(line)):
            current["ci_shrink"] = match.group("shrink")
        elif current and (match := ELAPSED_RE.match(line)):
            current["elapsed"] = match.group("elapsed")
    if current:
        rows.append(current)

    print("preset,label,hands,divergent,divergent_rate,avg_branches,random_delta,random_ci,enum_delta,enum_ci,enum_low,enum_high,ci_shrink,elapsed")
    for row in rows:
        print(",".join(str(row.get(k, "")) for k in (
            "preset", "label", "hands", "divergent", "divergent_rate", "avg_branches",
            "random_delta", "random_ci", "enum_delta", "enum_ci", "enum_low", "enum_high",
            "ci_shrink", "elapsed",
        )))


if __name__ == "__main__":
    main()

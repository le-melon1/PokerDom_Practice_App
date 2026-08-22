"""A/B test for CONFIDENCE_GATED_ARCHETYPE_READ (Tier 6 #2) using MANY
short, independent probe sessions instead of one long adaptive run.

Why this needed its own script: probe_chance_enumeration.py's normal
adaptive mode keeps ONE TableTurnover alive across the whole run (by
design -- every other opponent-signal flag this session, archetype,
freq_tier, tilt, bluff tier, wants that persistence). hands_played only
increments, never resets (no full after_hand()-style reseating happens
in the probe harness), so CONFIDENCE_GATED_ARCHETYPE_READ's "distrust an
archetype read below CONFIDENCE_MIN_HANDS" condition can only ever be
true during the first ~20 hands of an entire run -- for a 500k-hand
adaptive run that's a 0.004% window, structurally unreachable.

Fix: run MANY short (SESSION_LENGTH-hand) independent sessions, each
starting with a FRESH TableTurnover (hands_played=0), so every session
revisits the low-confidence window. Accumulates divergent hands and
deltas across sessions using the exact same _adaptive_stop_reason logic
and confirmed-real bar as every other test in this file.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.probe_chance_enumeration import (
    _adaptive_stop_reason,
    _all_test_groups,
    _build_comparison,
    _new_probe_state,
    _original_state_for,
    _print_probe_summary,
    _restore_flags,
    _run_probe_chunk,
    _stats,
)

PRESET = "confidence-gated-archetype-read"
SESSION_LENGTH = 25  # covers CONFIDENCE_MIN_HANDS=20 plus a small buffer


def run(
    base_seed: int,
    target_ci: float,
    effect_ratio: float,
    min_hands: int,
    max_hands: int,
    max_zero_divergent_hands: int,
    min_divergent: int,
    max_divergent: int,
) -> None:
    _, label = _all_test_groups()[PRESET]
    comparison = _build_comparison(PRESET, "current")
    original = _original_state_for(comparison)

    random_deltas: list[float] = []
    enum_deltas: list[float] = []
    branch_counts: list[int] = []
    divergent = 0
    n_hands = 0
    session_idx = 0
    stop_reason = None
    t0 = time.perf_counter()
    print(
        f"confidence-gate probe: {label} ({PRESET}), many independent {SESSION_LENGTH}-hand "
        f"sessions, base_seed={base_seed}, target_ci={target_ci}, effect_ratio={effect_ratio}, "
        f"min/max hands={min_hands}/{max_hands}, max_zero_divergent_hands={max_zero_divergent_hands}, "
        f"min/max divergent={min_divergent}/{max_divergent}",
        flush=True,
    )
    try:
        while n_hands < max_hands:
            # Fresh TableTurnover every session -- distinct archetype
            # population draw (varied rng_seed) but the SAME base_seed
            # feeds deck/bot-action seeding via hand_index=n_hands below,
            # preserving this project's usual seed42/seed777
            # reproducibility convention.
            turnover_seed = base_seed * 1_000_003 + session_idx
            base_table, treat_table, base_turnover, treat_turnover = _new_probe_state(None, turnover_seed)
            this_chunk = min(SESSION_LENGTH, max_hands - n_hands)
            divergent += _run_probe_chunk(
                comparison.baseline,
                comparison.treatment,
                base_table,
                treat_table,
                base_turnover,
                treat_turnover,
                n_hands,
                this_chunk,
                random_deltas,
                enum_deltas,
                branch_counts,
                None,
                base_seed,
                False,
            )
            n_hands += this_chunk
            session_idx += 1

            if session_idx % 200 == 0 or n_hands >= max_hands:
                random_delta, random_ci = _stats(random_deltas)
                enum_delta, enum_ci = _stats(enum_deltas)
                elapsed = time.perf_counter() - t0
                print(
                    f"progress sessions={session_idx} hands={n_hands} divergent={divergent} "
                    f"({divergent / n_hands * 100:.2f}%) random_delta={random_delta:+.2f} "
                    f"random_ci={random_ci:.2f} enum_delta={enum_delta:+.2f} enum_ci={enum_ci:.2f} "
                    f"elapsed={elapsed:.1f}s",
                    flush=True,
                )
                stop_reason = _adaptive_stop_reason(
                    n_hands,
                    divergent,
                    enum_delta,
                    enum_ci,
                    min_hands=min_hands,
                    max_hands=max_hands,
                    max_zero_divergent_hands=max_zero_divergent_hands,
                    min_divergent=min_divergent,
                    max_divergent=max_divergent,
                    target_ci=target_ci,
                    effect_ratio=effect_ratio,
                )
                if stop_reason:
                    break
    finally:
        _restore_flags(original)

    print(f"stop_reason: {stop_reason}", flush=True)
    _print_probe_summary(label, PRESET, n_hands, divergent, branch_counts, random_deltas, enum_deltas, time.perf_counter() - t0)


def main() -> None:
    args = sys.argv[1:]
    base_seed = int(args[0]) if args else 42
    run(
        base_seed=base_seed,
        target_ci=1.0,
        effect_ratio=0.5,
        min_hands=5000,
        max_hands=1_000_000,
        max_zero_divergent_hands=300_000,
        min_divergent=30,
        max_divergent=2000,
    )


if __name__ == "__main__":
    main()

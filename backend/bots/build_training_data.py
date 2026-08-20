"""Build the behavior-clone training dataset: one row per real decision point
(every action any player took, at any street), with the game-state features
available at that moment and the actual action taken as the label.

Re-walks each hand sequentially (like decision_points.py / vs_raise_stats.py
in the analysis project) because pot size, raise count, and board texture at
the moment of each action aren't columns in the flat actions.parquet -- they
have to be reconstructed in order.

2026-07-30: on the expanded dataset (34.5M actions), the original version
accumulated one Python dict per decision row in a single `rows` list before
one final pd.DataFrame(rows) call. Unlike actions_df/hands_df (already
loaded once as DataFrames -- columnar, ~660MB, proven safe), a list of ~30M+
Python dicts is not memory-efficient (per-dict/per-key overhead easily
multiplies out to many GB) -- the same class of OOM risk that hit main.py,
just one level removed from raw Hand objects instead of flat rows. Fixed the
same way: process hand_id groups in bounded batches, turn each batch into a
small DataFrame fragment and stream it straight to parquet via
pyarrow.parquet.ParquetWriter, and only ever hold one batch's rows at a time.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ANALYSIS_ROOT = Path(__file__).resolve().parents[3] / "PokerDom_Microlimits_Analysis"
sys.path.insert(0, str(ANALYSIS_ROOT))

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.pipeline.archetypes import label_archetypes
from src.pipeline.board_texture import texture_features
from src.pipeline.preprocess import player_stats

STREET_BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
HAND_BATCH_SIZE = 50_000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _hand_rows(
    hand_id, grp, board_by_hand: dict, archetype_by_player: dict, freq_tier_by_player: dict
) -> list[dict]:
    if grp["big_blind"].iloc[0] <= 0:
        return []  # same rare malformed/missed-blind hands filtered elsewhere in the analysis project

    board_str = board_by_hand.get(hand_id, "")
    board = board_str.split() if board_str else []

    # 2026-08 addition: was this player the last preflop raiser SO FAR, at
    # the moment of this decision? Same definition as the analysis project's
    # decision_points.py bettor_had_initiative and abc_bot.py's
    # _had_preflop_initiative -- both causal (only actions that have already
    # happened). Motivation: the ABC bot's own v17 DONK_BLUFF_VS_TIGHT
    # exploit exists BECAUSE real tight archetypes fold more to a donk lead
    # than an equally-sized continuation bet -- but the ML bots being
    # exploited have never had this feature, so they can't distinguish "I'm
    # continuation betting" from "I'm donk-leading."
    #
    # IMPORTANT (2026-08-08 fix): a first version of this computed
    # last_preflop_raiser ONCE from the whole hand's preflop raises (full
    # hindsight) and applied it to every row uniformly. That's a real
    # training/serving skew: live inference (_had_preflop_initiative) only
    # ever sees actions that have ALREADY happened, so for a preflop row
    # where this player opens and later gets 3-bet by someone else, the
    # leaky version would retroactively label their own opening-raise row as
    # had_initiative=False (since by hand's end, someone ELSE is the final
    # preflop raiser) -- info the player couldn't possibly have had yet. For
    # POSTFLOP rows the two computations coincide (preflop is fully resolved
    # by then), so this only distorted preflop rows -- but preflop is where
    # most rows live, and the first retrain showed suspiciously large
    # swings in hero's own preflop stats (PFR 14.8%->17%, hand-win-rate
    # 15.7%->20%) despite zero changes to hero's own logic, which is what
    # caught this. Fixed by tracking the running last-raiser incrementally
    # in the loop below, exactly like the live code does.
    preflop_last_raiser: str | None = None

    # Blinds aren't recorded as actions in this dataset -- seed the pot with
    # them (small_blind = big_blind / 2, the convention used throughout this
    # project) so pot_before is never ~0 right at the start of a hand, which
    # would otherwise make bet_frac_of_pot blow up for the first aggressive action.
    big_blind = grp["big_blind"].iloc[0]
    pot = big_blind * 1.5
    street_contributed: dict[str, float] = {}
    current_street_bet = 0.0
    current_street = "preflop"
    n_raises_this_street = 0
    # `stack` in actions_df is each player's STARTING stack for the whole
    # hand (preprocess.hands_to_frames sets it once per hand, not per
    # action) -- track how much each player has put in so far across ALL
    # streets to get their real remaining/effective stack at each decision
    # point. This is what was missing from this dataset before: real,
    # usable stack-depth data exists (PokerStars starting_stacks are real
    # dollar amounts, not `inf` -- only the small IPN sample had that),
    # it just was never turned into a feature, which is the likely cause
    # of the ML bots' "monster pot" behavior (no way to learn that real
    # players stop escalating bet sizes once SPR gets low).
    total_contributed: dict[str, float] = {}
    rows = []

    for row in grp.itertuples(index=False):
        if row.street != current_street:
            current_street = row.street
            street_contributed = {}
            current_street_bet = 0.0
            n_raises_this_street = 0

        board_len = STREET_BOARD_LEN.get(current_street, 0)
        texture = texture_features(board[:board_len]) if board_len else texture_features([])
        pot_before = max(pot, 1e-6)
        contributed_before = street_contributed.get(row.player, 0.0)
        to_call = max(current_street_bet - contributed_before, 0.0)

        archetype = archetype_by_player.get(row.player, "Insufficient sample")
        # 2026-08-20: real player's OWN measured tier, same field
        # label_archetypes() already computes (postflop_freq_tier) -- not a
        # population sample, this is ground truth for that specific real
        # player. "normal" fallback for anyone missing from the lookup
        # (shouldn't happen since both dicts come from the same stats df,
        # but matches choose_bot_action's own default rather than crashing).
        freq_tier = freq_tier_by_player.get(row.player, "normal")
        remaining_stack = max(row.stack - total_contributed.get(row.player, 0.0), 0.0)

        rows.append(
            {
                "hand_id": hand_id,
                "street": current_street,
                "position": row.position,
                "archetype": archetype,
                "freq_tier": freq_tier,
                "pot_before": pot_before,
                "to_call_frac": to_call / pot_before,
                "n_raises_this_street": n_raises_this_street,
                "had_initiative": row.player == preflop_last_raiser,
                "big_blind": row.big_blind,
                "stack_bb": remaining_stack / row.big_blind,
                "spr": remaining_stack / pot_before,
                "action": row.action,
                "amount": row.amount,
                "bet_frac_of_pot": (row.amount / pot_before) if row.action in ("bets", "raises") else 0.0,
                **{f"board_{k}": v for k, v in texture.items()},
            }
        )

        if row.action in ("calls",):
            street_contributed[row.player] = contributed_before + row.amount
            total_contributed[row.player] = total_contributed.get(row.player, 0.0) + row.amount
            pot += row.amount
        elif row.action in ("bets", "raises"):
            increment = row.amount
            street_contributed[row.player] = contributed_before + increment
            total_contributed[row.player] = total_contributed.get(row.player, 0.0) + increment
            current_street_bet = max(current_street_bet, street_contributed[row.player])
            n_raises_this_street += 1
            pot += increment
            if current_street == "preflop" and row.action == "raises":
                preflop_last_raiser = row.player

    return rows


def build_dataset_streaming(
    actions_df: pd.DataFrame,
    hands_df: pd.DataFrame,
    archetype_by_player: dict,
    freq_tier_by_player: dict,
    out_path: Path,
) -> int:
    """Streams the training dataset straight to `out_path` in bounded
    hand-count batches, never holding more than one batch's decision rows in
    memory at once. Returns the total row count written."""
    board_by_hand = dict(zip(hands_df["hand_id"], hands_df["board"]))
    writer = None
    batch_rows: list[dict] = []
    n_hands = 0
    total_rows = 0

    def _flush():
        nonlocal writer, batch_rows, total_rows
        if not batch_rows:
            return
        frag = pd.DataFrame(batch_rows)
        table = pa.Table.from_pandas(frag, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(str(out_path), table.schema)
        writer.write_table(table)
        total_rows += len(batch_rows)
        batch_rows = []

    for hand_id, grp in actions_df.groupby("hand_id", sort=False):
        batch_rows.extend(_hand_rows(hand_id, grp, board_by_hand, archetype_by_player, freq_tier_by_player))
        n_hands += 1
        if n_hands % HAND_BATCH_SIZE == 0:
            _flush()
            log(f"processed {n_hands} hands, {total_rows} decision rows written so far")

    _flush()
    if writer is not None:
        writer.close()
    log(f"done: {total_rows} decision rows written to {out_path}")
    return total_rows


def main():
    log("loading actions/hands parquet...")
    actions_df = pd.read_parquet(ANALYSIS_ROOT / "data/processed/actions.parquet")
    hands_df = pd.read_parquet(ANALYSIS_ROOT / "data/processed/hands.parquet")

    log("labeling archetypes...")
    stats = label_archetypes(player_stats(actions_df))
    archetype_by_player = dict(zip(stats["player"], stats["archetype"]))
    freq_tier_by_player = dict(zip(stats["player"], stats["postflop_freq_tier"]))

    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "behavior_clone_training_data.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"building decision dataset from {len(actions_df)} actions, streaming to {out_path}...")
    build_dataset_streaming(actions_df, hands_df, archetype_by_player, freq_tier_by_player, out_path)


if __name__ == "__main__":
    main()

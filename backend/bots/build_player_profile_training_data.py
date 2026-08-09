"""Build a decision-point training dataset for "real player" bots: unlike
build_training_data.py (pooled across the whole population, archetype-only
conditioning), this restricts to ONLY the ~20 real players selected in
PokerDom_Microlimits_Analysis/data/reference/player_profile_seeds.csv
(scripts/select_player_profiles.py), and adds each player's own continuous
stat profile (vpip/pfr/aggression_factor) plus a causal within-session
position feature -- hands already played by THIS specific player in their
current real session, resetting at every real 45-minute-gap session
boundary. That second half is the point of the project: not just "how does
this player play a given hand," but "how does their play drift across a
session" (the sibling repo's within-session-adaptation finding, applied
per-individual instead of at the population level).

session_hands_so_far is deliberately the exact same causal quantity as
backend/sessions/live_dynamics.py's SeatOccupant.hands_played -- computed
here from real historical timestamps, tracked live the same way at serving
time, so training and serving never disagree about what this feature means
(the exact class of bug the had_initiative feature hit once already, see
build_training_data.py's docstring).

Reuses build_training_data.py's per-hand state-reconstruction walk (pot
size, stack depth, board texture, had_initiative) but only emits rows for
the chosen players' own decisions, and only walks hands where at least one
chosen player acted -- a small fraction of the 3.56M-hand dataset.
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

from src.pipeline.board_texture import texture_features

STREET_BOARD_LEN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
HAND_BATCH_SIZE = 20_000
SESSION_GAP_MINUTES = 45


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _assign_session_hands_so_far(player_hand_times: pd.DataFrame) -> pd.DataFrame:
    """player_hand_times: columns [player, hand_id, timestamp]. Returns the
    same with an added `session_hands_so_far` column -- a 0-indexed count of
    hands this player has ALREADY played in their current real session
    before this hand, resetting at every >45min gap. Purely causal: only
    ever counts hands earlier in the same sorted sequence."""
    out = []
    for player, grp in player_hand_times.groupby("player", sort=False):
        grp = grp.sort_values("timestamp")
        gap_minutes = grp["timestamp"].diff().dt.total_seconds().fillna(0) / 60.0
        new_session = gap_minutes > SESSION_GAP_MINUTES
        session_id = new_session.cumsum()
        hands_so_far = grp.groupby(session_id).cumcount()
        grp = grp.assign(session_hands_so_far=hands_so_far.values)
        out.append(grp)
    return pd.concat(out, ignore_index=True)


def _hand_rows(
    hand_id,
    grp,
    board_by_hand: dict,
    chosen_players: set,
    session_feature_by_hand_player: dict,
    profile_by_player: dict,
) -> list[dict]:
    if grp["big_blind"].iloc[0] <= 0:
        return []

    board_str = board_by_hand.get(hand_id, "")
    board = board_str.split() if board_str else []

    preflop_last_raiser: str | None = None
    big_blind = grp["big_blind"].iloc[0]
    pot = big_blind * 1.5
    street_contributed: dict[str, float] = {}
    current_street_bet = 0.0
    current_street = "preflop"
    n_raises_this_street = 0
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
        remaining_stack = max(row.stack - total_contributed.get(row.player, 0.0), 0.0)

        if row.player in chosen_players:
            profile = profile_by_player[row.player]
            session_hands_so_far = session_feature_by_hand_player.get((hand_id, row.player), 0)
            rows.append(
                {
                    "hand_id": hand_id,
                    "player": row.player,
                    "profile_id": profile["profile_id"],
                    "archetype": profile["archetype"],
                    "player_vpip": profile["vpip"],
                    "player_pfr": profile["pfr"],
                    "player_af": profile["aggression_factor"],
                    "session_hands_so_far": session_hands_so_far,
                    "street": current_street,
                    "position": row.position,
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


def main():
    seeds_path = ANALYSIS_ROOT / "data/reference/player_profile_seeds.csv"
    seeds = pd.read_csv(seeds_path)
    chosen_players = set(seeds["player"])
    profile_by_player = {
        row["player"]: {
            "profile_id": row["profile_id"],
            "archetype": row["archetype"],
            "vpip": row["vpip"],
            "pfr": row["pfr"],
            "aggression_factor": row["aggression_factor"],
        }
        for _, row in seeds.iterrows()
    }
    log(f"{len(chosen_players)} chosen players loaded from {seeds_path}")

    log("loading actions.parquet...")
    actions_full = pd.read_parquet(ANALYSIS_ROOT / "data/processed/actions.parquet")
    log(f"{len(actions_full)} total actions loaded")
    chosen_hand_ids = set(actions_full.loc[actions_full["player"].isin(chosen_players), "hand_id"])
    log(f"{len(chosen_hand_ids)} hands touch at least one chosen player")
    actions_df = actions_full[actions_full["hand_id"].isin(chosen_hand_ids)].copy()
    del actions_full

    log("loading hands.parquet (board) + hand_timestamps.parquet...")
    hands_df = pd.read_parquet(ANALYSIS_ROOT / "data/processed/hands.parquet", columns=["hand_id", "board"])
    board_by_hand = dict(zip(hands_df["hand_id"], hands_df["board"]))

    timestamps = pd.read_parquet(
        ANALYSIS_ROOT / "data/processed/hand_timestamps.parquet", columns=["hand_id", "timestamp"]
    )
    player_hand_times = actions_df.loc[actions_df["player"].isin(chosen_players), ["player", "hand_id"]].drop_duplicates()
    player_hand_times = player_hand_times.merge(timestamps, on="hand_id", how="inner")
    player_hand_times["timestamp"] = pd.to_datetime(player_hand_times["timestamp"])
    log(f"{len(player_hand_times)} (player, hand) rows with timestamps for session tracking")

    player_hand_times = _assign_session_hands_so_far(player_hand_times)
    session_feature_by_hand_player = {
        (row.hand_id, row.player): row.session_hands_so_far for row in player_hand_times.itertuples(index=False)
    }
    log("session_hands_so_far computed")

    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "player_profile_training_data.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

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

    log(f"walking {len(chosen_hand_ids)} hands...")
    for hand_id, grp in actions_df.groupby("hand_id", sort=False):
        batch_rows.extend(
            _hand_rows(hand_id, grp, board_by_hand, chosen_players, session_feature_by_hand_player, profile_by_player)
        )
        n_hands += 1
        if n_hands % HAND_BATCH_SIZE == 0:
            _flush()
            log(f"processed {n_hands}/{len(chosen_hand_ids)} hands, {total_rows} decision rows so far")

    _flush()
    if writer is not None:
        writer.close()
    log(f"done: {total_rows} decision rows written to {out_path}")


if __name__ == "__main__":
    main()

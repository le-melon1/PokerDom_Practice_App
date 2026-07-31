"""Train the behavior-clone bot: two CatBoost models.

1. Action-type classifier: fold/check/call/bet/raise, given street, position,
   archetype, pot odds, raise count, board texture.
2. Sizing classifier: for bet/raise rows only, small/medium/large pot-fraction
   bucket (same thresholds used throughout the analysis project: <0.4/0.4-0.7/>0.7).

Two stages instead of one big multi-class-with-sizing model because sizing is
only meaningful conditional on having bet/raised -- keeps each model's target
distribution clean rather than forcing "fold" and "raise-to-2.5x-pot" into the
same flat label space.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import train_test_split

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "behavior_clone_training_data.parquet"
MODEL_DIR = Path(__file__).resolve().parents[2] / "data"

CAT_FEATURES = ["street", "position", "archetype"]
# 2026-07-30: tried adding stack_bb/spr here (real stack-depth data exists in
# build_training_data.py's output, computed but unused) hoping it would fix
# the ML bots' "monster pot" tendency. Measured result: monster-pot rate was
# UNCHANGED (~21-22%, same as before) and the non-monster-pot winrate got
# WORSE across the board (+6-7 bb/100 vs the prior +12-14 bb/100 baseline --
# see abc_bot.py's v11 note and scripts/simulate_abc_bot.py's history for the
# comparison). Reverted -- these features stayed unused in the trained
# models. Root cause guess for why it didn't help: the models reset to
# 200bb every hand in the simulation, and a single "large"-bucket bet in a
# MULTIWAY pot balloons the pot past the 50bb "monster" threshold long before
# any individual player's remaining stack looks unusually short -- a
# per-player stack feature doesn't capture that dynamic. Left as an
# unresolved, real finding for a future session with a clearer head, not
# something to keep guessing at live. If revisiting: a pot-relative (not
# stack-relative) cap, or capping across ALL live players' effective
# stacks, is a more promising angle than what was tried here.
NUMERIC_FEATURES = [
    "to_call_frac",
    "n_raises_this_street",
    "board_board_paired",
    "board_board_monotone",
    "board_board_two_tone",
    "board_board_max_suit_count",
    "board_board_connectedness",
    "board_board_high_card",
]
FEATURES = CAT_FEATURES + NUMERIC_FEATURES


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def train_action_model(df: pd.DataFrame) -> CatBoostClassifier:
    train_df, eval_df = train_test_split(df, test_size=0.1, random_state=42, stratify=df["action"])
    train_pool = Pool(train_df[FEATURES], train_df["action"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[FEATURES], eval_df["action"], cat_features=CAT_FEATURES)

    model = CatBoostClassifier(
        iterations=200,
        depth=6,
        learning_rate=0.12,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        verbose=20,
        random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    return model


def train_sizing_model(df: pd.DataFrame) -> CatBoostClassifier:
    bets = df[df["action"].isin(["bets", "raises"])].copy()
    bins = [0, 0.4, 0.7, float("inf")]
    labels = ["small", "medium", "large"]
    bets["size_bucket"] = pd.cut(bets["bet_frac_of_pot"], bins=bins, labels=labels)
    bets = bets.dropna(subset=["size_bucket"])

    train_df, eval_df = train_test_split(
        bets, test_size=0.1, random_state=42, stratify=bets["size_bucket"]
    )
    train_pool = Pool(train_df[FEATURES], train_df["size_bucket"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[FEATURES], eval_df["size_bucket"], cat_features=CAT_FEATURES)

    model = CatBoostClassifier(
        iterations=200,
        depth=6,
        learning_rate=0.12,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        verbose=20,
        random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    return model


SAMPLE_SIZE = 1_000_000  # full 8M-row set made Pool/train_test_split pathologically
# slow on this machine (confirmed 200k rows trains in ~6s; full set didn't finish
# basic setup in several minutes) -- 1M rows is plenty for a behavior clone and
# keeps this tractable overnight.


def main():
    log(f"loading training data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    if len(df) > SAMPLE_SIZE:
        df = df.sample(n=SAMPLE_SIZE, random_state=42).reset_index(drop=True)
    for c in CAT_FEATURES:
        df[c] = df[c].astype(str)
    log(f"loaded {len(df)} rows (sampled), action distribution:\n{df['action'].value_counts()}")

    log("training action-type model...")
    action_model = train_action_model(df)
    action_model.save_model(str(MODEL_DIR / "behavior_clone_action.cbm"))
    log("saved behavior_clone_action.cbm")

    log("training sizing model...")
    sizing_model = train_sizing_model(df)
    sizing_model.save_model(str(MODEL_DIR / "behavior_clone_sizing.cbm"))
    log("saved behavior_clone_sizing.cbm")

    log("ALL DONE")


if __name__ == "__main__":
    main()

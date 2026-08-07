"""One-off comparison: does adding `had_initiative` (was this player the last
preflop raiser) as a feature improve the behavior-clone models' held-out
prediction quality? Trains both the action-type and sizing models twice --
once with the pre-2026-08 feature set, once with had_initiative added -- on
the SAME train/test split (random_state=42, matching train_behavior_clone.py
exactly) so the comparison is apples-to-apples, and reports each model's
best held-out MultiClass loss (lower is better; this is what CatBoost's
use_best_model=True already selects on).

Does not touch the shipped .cbm files -- purely a measurement.

Usage: python3 scripts/compare_had_initiative_feature.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import train_test_split

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "behavior_clone_training_data.parquet"
CAT_FEATURES = ["street", "position", "archetype"]
NUMERIC_BASE = [
    "to_call_frac",
    "n_raises_this_street",
    "board_board_paired",
    "board_board_monotone",
    "board_board_two_tone",
    "board_board_max_suit_count",
    "board_board_connectedness",
    "board_board_high_card",
]
SAMPLE_SIZE = 1_000_000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def train_and_eval_action(df: pd.DataFrame, features: list[str], label: str) -> float:
    train_df, eval_df = train_test_split(df, test_size=0.1, random_state=42, stratify=df["action"])
    train_pool = Pool(train_df[features], train_df["action"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[features], eval_df["action"], cat_features=CAT_FEATURES)
    model = CatBoostClassifier(
        iterations=200, depth=6, learning_rate=0.12,
        loss_function="MultiClass", eval_metric="MultiClass",
        verbose=False, random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    score = model.get_best_score()["validation"]["MultiClass"]
    log(f"[action model, {label}] held-out MultiClass loss: {score:.5f} (best iter {model.get_best_iteration()})")
    return score


def train_and_eval_sizing(df: pd.DataFrame, features: list[str], label: str) -> float:
    bets = df[df["action"].isin(["bets", "raises"])].copy()
    bins = [0, 0.4, 0.7, float("inf")]
    labels = ["small", "medium", "large"]
    bets["size_bucket"] = pd.cut(bets["bet_frac_of_pot"], bins=bins, labels=labels)
    bets = bets.dropna(subset=["size_bucket"])
    train_df, eval_df = train_test_split(bets, test_size=0.1, random_state=42, stratify=bets["size_bucket"])
    train_pool = Pool(train_df[features], train_df["size_bucket"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[features], eval_df["size_bucket"], cat_features=CAT_FEATURES)
    model = CatBoostClassifier(
        iterations=200, depth=6, learning_rate=0.12,
        loss_function="MultiClass", eval_metric="MultiClass",
        verbose=False, random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    score = model.get_best_score()["validation"]["MultiClass"]
    log(f"[sizing model, {label}] held-out MultiClass loss: {score:.5f} (best iter {model.get_best_iteration()})")
    return score


def main():
    log(f"loading {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    df = df.sample(n=SAMPLE_SIZE, random_state=42).reset_index(drop=True)
    for c in CAT_FEATURES:
        df[c] = df[c].astype(str)
    df["had_initiative"] = df["had_initiative"].astype(int)
    log(f"sampled {len(df)} rows")

    features_without = CAT_FEATURES + NUMERIC_BASE
    features_with = CAT_FEATURES + NUMERIC_BASE + ["had_initiative"]

    log("=== ACTION MODEL ===")
    loss_action_without = train_and_eval_action(df, features_without, "WITHOUT had_initiative")
    loss_action_with = train_and_eval_action(df, features_with, "WITH had_initiative")

    log("=== SIZING MODEL ===")
    loss_sizing_without = train_and_eval_sizing(df, features_without, "WITHOUT had_initiative")
    loss_sizing_with = train_and_eval_sizing(df, features_with, "WITH had_initiative")

    log("=== SUMMARY (lower loss = better held-out prediction) ===")
    log(f"action model:  without={loss_action_without:.5f}  with={loss_action_with:.5f}  "
        f"delta={loss_action_with - loss_action_without:+.5f}")
    log(f"sizing model:  without={loss_sizing_without:.5f}  with={loss_sizing_with:.5f}  "
        f"delta={loss_sizing_with - loss_sizing_without:+.5f}")


if __name__ == "__main__":
    main()

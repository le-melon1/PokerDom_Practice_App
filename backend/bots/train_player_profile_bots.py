"""Train the "real player" behavior-clone bots: same two-CatBoost-model
architecture as train_behavior_clone.py (action-type classifier + sizing
classifier), but on backend/bots/build_player_profile_training_data.py's
output -- decision points from ONLY the ~20 real players in
PokerDom_Microlimits_Analysis/data/reference/player_profile_seeds.csv,
conditioned on:

  - profile_id (categorical, one of the 20 real players) instead of the
    6-bucket archetype -- lets the model learn each individual's own
    tendencies rather than averaging them into a coarse category.
  - player_vpip/player_pfr/player_af (that specific player's own real
    aggregate stats) as numeric features alongside profile_id, so the model
    has an explicit statistical fingerprint to generalize from, not just an
    opaque category id.
  - session_hands_so_far (causal, resets each real detected session) -- the
    "behavior across the whole session" feature. This is the model's only
    signal for within-session drift; whether it actually learns anything
    from it (vs. treating it as noise) is exactly what needs checking after
    training, e.g. via CatBoost's own feature importances.

Much smaller dataset than the population model (a few hundred thousand rows
across 20 players, not 34M+ across the whole population) -- no need for
train_behavior_clone.py's SAMPLE_SIZE downsampling.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.model_selection import train_test_split

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "player_profile_training_data.parquet"
MODEL_DIR = Path(__file__).resolve().parents[2] / "data"

CAT_FEATURES = ["street", "position", "profile_id"]
NUMERIC_FEATURES = [
    "to_call_frac",
    "n_raises_this_street",
    "board_board_paired",
    "board_board_monotone",
    "board_board_two_tone",
    "board_board_max_suit_count",
    "board_board_connectedness",
    "board_board_high_card",
    "had_initiative",
    "player_vpip",
    "player_pfr",
    "player_af",
    "session_hands_so_far",
]
FEATURES = CAT_FEATURES + NUMERIC_FEATURES


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def train_action_model(df: pd.DataFrame) -> CatBoostClassifier:
    train_df, eval_df = train_test_split(df, test_size=0.1, random_state=42, stratify=df["action"])
    train_pool = Pool(train_df[FEATURES], train_df["action"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[FEATURES], eval_df["action"], cat_features=CAT_FEATURES)

    model = CatBoostClassifier(
        iterations=300,
        depth=6,
        learning_rate=0.1,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        verbose=25,
        random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    log("action model feature importances:")
    for name, imp in sorted(zip(FEATURES, model.get_feature_importance(train_pool)), key=lambda x: -x[1]):
        log(f"  {name}: {imp:.2f}")
    return model


def train_sizing_model(df: pd.DataFrame) -> CatBoostClassifier:
    bets = df[df["action"].isin(["bets", "raises"])].copy()
    bins = [0, 0.4, 0.7, float("inf")]
    labels = ["small", "medium", "large"]
    bets["size_bucket"] = pd.cut(bets["bet_frac_of_pot"], bins=bins, labels=labels)
    bets = bets.dropna(subset=["size_bucket"])

    train_df, eval_df = train_test_split(bets, test_size=0.1, random_state=42, stratify=bets["size_bucket"])
    train_pool = Pool(train_df[FEATURES], train_df["size_bucket"], cat_features=CAT_FEATURES)
    eval_pool = Pool(eval_df[FEATURES], eval_df["size_bucket"], cat_features=CAT_FEATURES)

    model = CatBoostClassifier(
        iterations=300,
        depth=6,
        learning_rate=0.1,
        loss_function="MultiClass",
        eval_metric="MultiClass",
        verbose=25,
        random_state=42,
    )
    model.fit(train_pool, eval_set=eval_pool, use_best_model=True)
    log("sizing model feature importances:")
    for name, imp in sorted(zip(FEATURES, model.get_feature_importance(train_pool)), key=lambda x: -x[1]):
        log(f"  {name}: {imp:.2f}")
    return model


def main():
    log(f"loading training data from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    for c in CAT_FEATURES:
        df[c] = df[c].astype(str)
    df["had_initiative"] = df["had_initiative"].astype(int)
    log(f"loaded {len(df)} rows, {df['profile_id'].nunique()} profiles")
    log(f"action distribution:\n{df['action'].value_counts()}")
    log(f"rows per profile:\n{df['profile_id'].value_counts().sort_index()}")

    log("training action-type model...")
    action_model = train_action_model(df)
    action_model.save_model(str(MODEL_DIR / "player_profile_action.cbm"))
    log("saved player_profile_action.cbm")

    log("training sizing model...")
    sizing_model = train_sizing_model(df)
    sizing_model.save_model(str(MODEL_DIR / "player_profile_sizing.cbm"))
    log("saved player_profile_sizing.cbm")

    log("ALL DONE")


if __name__ == "__main__":
    main()

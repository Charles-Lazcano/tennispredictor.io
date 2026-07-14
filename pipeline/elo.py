#!/usr/bin/env python3
"""
Phase 3: rolling ~3-year-window Elo (global + surface-specific, blended),
recent-form feature, and age as a standalone feature.

Rolling-window design
----------------------
A true walk-forward "3-year window" means a player's rating at any point in
time must depend only on matches from the trailing 3 years - never on their
whole career, and never on the future. Doing that by literally recomputing
Elo from scratch before every single match would be O(n * window) and slow
to the point of being impractical here, so this uses a checkpoint scheme:

  - The timeline is split into calendar quarters.
  - At the start of each quarter Q, ratings are recomputed FROM SCRATCH using
    only matches whose date falls in [Q_start - 3 years, Q_start) - i.e. a
    clean windowed base rating with no leakage from outside the window.
  - Matches within quarter Q are then replayed in order on top of that base,
    with the usual incremental Elo update, recording each match's PRE-match
    rating (never post-match) as the feature value.

This keeps the "only last 3 years matter" property while being O(n) overall
(each match is processed roughly twice: once as part of a windowed-base
recompute, once during its own quarter's sequential replay).

Surface Elo uses the identical scheme, filtered to same-surface matches only.
"Blended" Elo = 0.5*global + 0.5*surface; the two are also kept as separate
diff features (elo_diff, elo_diff_surface) since the downstream logistic
regression can already learn its own blend - matches the existing app's
feature architecture.

Recent-form feature = trailing rolling win% over the player's last 12 matches
(midpoint of the requested 10-15), tracked with a simple per-player deque -
this window is naturally "last N matches" rather than time-based, so no
checkpoint scheme is needed for it.

Age is left untouched as a raw column (winner_age/loser_age already present
in the TennisMyLife data) - deliberately NOT folded into Elo, so the model
can learn an age-performance relationship on its own.
"""
from collections import defaultdict, deque

import numpy as np
import pandas as pd

from pipeline.common import MASTER_DIR

WINDOW_YEARS = 3
WINDOW_DAYS = 365 * WINDOW_YEARS
FORM_WINDOW = 12  # trailing matches for recent-form win%
K = 40.0
SURFACES = ["Hard", "Clay", "Grass", "Carpet"]


def _expected(Ra, Rb):
    return 1.0 / (1.0 + 10 ** ((Rb - Ra) / 400.0))


def _windowed_base_ratings(df_window: pd.DataFrame, by_surface: bool):
    """Replay df_window (already sorted, already filtered to the trailing window) from a
    cold start (1500) and return the resulting end-of-window rating per player
    (per surface, if by_surface)."""
    if not by_surface:
        ratings = defaultdict(lambda: 1500.0)
        for w, l in zip(df_window["winner_id"], df_window["loser_id"]):
            Ew = _expected(ratings[w], ratings[l])
            ratings[w] += K * (1.0 - Ew)
            ratings[l] -= K * (1.0 - Ew)
        return ratings
    ratings = {s: defaultdict(lambda: 1500.0) for s in SURFACES}
    for w, l, s in zip(df_window["winner_id"], df_window["loser_id"], df_window["surface"]):
        if s not in ratings:
            continue
        R = ratings[s]
        Ew = _expected(R[w], R[l])
        R[w] += K * (1.0 - Ew)
        R[l] -= K * (1.0 - Ew)
    return ratings


def compute_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["tourney_date", "tourney_id", "match_num"]).reset_index(drop=True)
    df["quarter"] = df["tourney_date"].dt.to_period("Q")

    global_ratings = defaultdict(lambda: 1500.0)
    surface_ratings = {s: defaultdict(lambda: 1500.0) for s in SURFACES}
    form_history = defaultdict(lambda: deque(maxlen=FORM_WINDOW))

    out_cols = {
        "winner_elo": [], "loser_elo": [],
        "winner_elo_surface": [], "loser_elo_surface": [],
        "winner_form": [], "loser_form": [],
    }

    quarters = df["quarter"].unique()
    for q in quarters:
        q_start = q.start_time
        window_start = q_start - pd.Timedelta(days=WINDOW_DAYS)
        window_mask = (df["tourney_date"] >= window_start) & (df["tourney_date"] < q_start)
        window_df = df[window_mask]

        # rebase global + surface ratings from a clean windowed recompute (no history leakage)
        global_ratings = _windowed_base_ratings(window_df, by_surface=False)
        surf_base = _windowed_base_ratings(window_df, by_surface=True)
        surface_ratings = {s: surf_base[s] for s in SURFACES}

        q_idx = df.index[df["quarter"] == q]
        for i in q_idx:
            w, l, s = df.at[i, "winner_id"], df.at[i, "loser_id"], df.at[i, "surface"]

            out_cols["winner_elo"].append(global_ratings[w])
            out_cols["loser_elo"].append(global_ratings[l])
            if s in surface_ratings:
                out_cols["winner_elo_surface"].append(surface_ratings[s][w])
                out_cols["loser_elo_surface"].append(surface_ratings[s][l])
            else:
                out_cols["winner_elo_surface"].append(np.nan)
                out_cols["loser_elo_surface"].append(np.nan)

            wf = form_history[w]
            lf = form_history[l]
            out_cols["winner_form"].append(np.mean(wf) if wf else np.nan)
            out_cols["loser_form"].append(np.mean(lf) if lf else np.nan)

            # apply updates AFTER recording pre-match values (no lookahead)
            Ew_g = _expected(global_ratings[w], global_ratings[l])
            global_ratings[w] += K * (1.0 - Ew_g)
            global_ratings[l] -= K * (1.0 - Ew_g)

            if s in surface_ratings:
                Ew_s = _expected(surface_ratings[s][w], surface_ratings[s][l])
                surface_ratings[s][w] += K * (1.0 - Ew_s)
                surface_ratings[s][l] -= K * (1.0 - Ew_s)

            form_history[w].append(1)
            form_history[l].append(0)

    for col, values in out_cols.items():
        df[col] = values

    df["elo_diff"] = df["winner_elo"] - df["loser_elo"]
    df["elo_diff_surface"] = df["winner_elo_surface"] - df["loser_elo_surface"]
    df["winner_elo_blended"] = 0.5 * df["winner_elo"] + 0.5 * df["winner_elo_surface"].fillna(df["winner_elo"])
    df["loser_elo_blended"] = 0.5 * df["loser_elo"] + 0.5 * df["loser_elo_surface"].fillna(df["loser_elo"])
    df["elo_diff_blended"] = df["winner_elo_blended"] - df["loser_elo_blended"]
    df["form_diff"] = df["winner_form"] - df["loser_form"]

    return df.drop(columns=["quarter"])


def main():
    primary_path = MASTER_DIR / "matches_primary_atp250plus.csv"
    df = pd.read_csv(primary_path, low_memory=False, parse_dates=["tourney_date"])
    df = df.dropna(subset=["winner_id", "loser_id", "surface", "tourney_date"])
    print(f"[i] Computing rolling {WINDOW_YEARS}-year-window Elo + form over {len(df):,} matches "
          f"(this replays each quarter's trailing window, expect ~1-3 min)...")

    df = compute_rolling_features(df)

    out_path = MASTER_DIR / "matches_with_features.csv"
    df.to_csv(out_path, index=False)
    print(f"[OK] matches_with_features.csv written -> {out_path}  ({len(df):,} rows)")

    latest_date = df["tourney_date"].max()
    cutoff = latest_date - pd.Timedelta(days=30)
    recent = df[df["tourney_date"] >= cutoff]
    top = pd.concat([
        recent[["winner_id", "winner_name", "winner_elo"]].rename(columns={"winner_id": "id", "winner_name": "name", "winner_elo": "elo"}),
        recent[["loser_id", "loser_name", "loser_elo"]].rename(columns={"loser_id": "id", "loser_name": "name", "loser_elo": "elo"}),
    ]).drop_duplicates(subset=["id"], keep="last").sort_values("elo", ascending=False).head(10)
    print("[i] Sample current top-10 by rolling-window Elo (most recent snapshot per player):")
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()

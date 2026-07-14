#!/usr/bin/env python3
"""
Phase 5: rolling accuracy report.

Step 23 (true walk-forward only): only 'true_forward' rows from the
predictions table are eligible - see pipeline/daily_scan.py's docstring for
why every prediction logged so far is 'same_day_fast_turnaround' instead
(TennisMyLife's feed has no upcoming-schedule source, so a prediction can't
yet be made before the match exists in any feed). This report will report
those separately and clearly, and will NOT blend them into the walk-forward
number - that would be exactly the "report accuracy without being honest
about backtesting" the user explicitly ruled out.

Step 24: every accuracy number is reported next to a baseline (naive
ranking-based favorite) - never as a raw number alone.

Step 25: broken out by surface and by tour level, not just one blended figure.
"""
import sqlite3

import pandas as pd

from pipeline.common import MASTER_DIR
from pipeline.db import DB_PATH


def load_predictions_with_context():
    conn = sqlite3.connect(DB_PATH)
    preds = pd.read_sql_query(
        """
        SELECT p.*, r.actual_winner_id, r.recorded_at, r.tourney_id AS result_tourney_id,
               r.match_num AS result_match_num
        FROM predictions p
        LEFT JOIN results r
          ON p.match_date = r.match_date
         AND p.player_a_id = r.player_a_id
         AND p.player_b_id = r.player_b_id
        """,
        conn,
    )
    conn.close()

    matches = pd.read_csv(MASTER_DIR / "matches_primary_atp250plus.csv", low_memory=False)
    matches = matches[["tourney_id", "match_num", "surface", "tourney_level",
                        "winner_rank", "loser_rank", "winner_id", "loser_id"]]
    matches["match_num"] = matches["match_num"].astype("Int64")
    preds["result_match_num"] = preds["result_match_num"].astype("Int64")

    # join match context via the RESULTS row's tourney_id/match_num - a true_forward
    # prediction's own tourney_id/match_num stay NULL forever (unknown at prediction
    # time, and predictions rows are never edited after the fact)
    df = preds.merge(
        matches, left_on=["result_tourney_id", "result_match_num"],
        right_on=["tourney_id", "match_num"], how="left", suffixes=("", "_match"),
    )
    df["pending"] = df["actual_winner_id"].isna()
    df["model_correct"] = None
    resolved = ~df["pending"]
    df.loc[resolved, "model_correct"] = (
        df.loc[resolved, "predicted_winner_id"] == df.loc[resolved, "actual_winner_id"]
    ).astype(int)

    # ranking-based naive baseline: "the better-ranked player wins" (lower rank number = better)
    def baseline_pred(row):
        wr, lr = row.get("winner_rank"), row.get("loser_rank")
        if pd.isna(wr) or pd.isna(lr) or wr == lr:
            return None
        favorite_is_winner = wr < lr  # winner actually had the better (lower) rank
        return int(favorite_is_winner)

    df["baseline_correct"] = df.apply(baseline_pred, axis=1)
    return df


def summarize(df: pd.DataFrame, label: str):
    if df.empty:
        print(f"[{label}] no eligible predictions yet")
        return
    pending = int(df["pending"].sum())
    resolved = df[~df["pending"]]
    if resolved.empty:
        print(f"[{label}] n={len(df)}  ({pending} pending - match(es) not yet played, no accuracy yet)")
        return
    model_acc = resolved["model_correct"].astype(float).mean()
    baseline_df = resolved.dropna(subset=["baseline_correct"])
    baseline_acc = baseline_df["baseline_correct"].mean() if len(baseline_df) else float("nan")
    print(f"[{label}] n={len(resolved)} resolved (+{pending} pending)  model_acc={model_acc:.3f}  "
          f"ranking_baseline_acc={baseline_acc:.3f}  (baseline n={len(baseline_df)})")


def main():
    df = load_predictions_with_context()
    true_forward = df[df["prediction_type"] == "true_forward"]
    fast_turnaround = df[df["prediction_type"] == "same_day_fast_turnaround"]

    print("=" * 70)
    print("WALK-FORWARD ACCURACY (true_forward only - the only number that")
    print("can honestly be called walk-forward, per the user's requirement)")
    print("=" * 70)
    summarize(true_forward, "true_forward - ALL")
    if true_forward.empty:
        print("  -> No true_forward predictions exist yet: TennisMyLife exposes no")
        print("     upcoming-schedule feed, so no prediction has ever been made before")
        print("     its match's outcome already existed in our data. See README.")
    else:
        for surface, sub in true_forward.groupby("surface"):
            summarize(sub, f"true_forward - surface={surface}")
        for level, sub in true_forward.groupby("tourney_level"):
            summarize(sub, f"true_forward - tourney_level={level}")

    print()
    print("=" * 70)
    print("SAME-DAY FAST-TURNAROUND (informational only - NOT walk-forward;")
    print("predictions made using pre-match features, but after the match's")
    print("result already existed in the source feed)")
    print("=" * 70)
    summarize(fast_turnaround, "same_day_fast_turnaround - ALL")
    if not fast_turnaround.empty:
        for surface, sub in fast_turnaround.groupby("surface"):
            summarize(sub, f"same_day_fast_turnaround - surface={surface}")
        for level, sub in fast_turnaround.groupby("tourney_level"):
            summarize(sub, f"same_day_fast_turnaround - tourney_level={level}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Phase 1, steps 1 + 4: scan TML-Database match files for name inconsistencies
(same canonical id showing up under >1 spelling) and dedupe on (tourney_id, match_num) -
the natural unique key for a match - never on player name.

Reads every TML-Database/<year>.csv (1968-2025) plus ongoing_tourneys.csv, all of which
already carry canonical winner_id/loser_id directly (see build_canonical.py for why no
fuzzy matching is needed for this source).

Outputs:
  data/master/matches_master.csv                 (deduped, canonical-id-bearing matches)
  data/review/match_name_inconsistencies.csv      (id -> multiple observed name spellings)
  data/review/match_duplicates_removed.csv        (rows dropped by the (tourney_id, match_num) dedupe)
"""
import glob
import pandas as pd

from pipeline.common import TML, MASTER_DIR, REVIEW_DIR, parse_yyyymmdd

YEAR_COLS = [
    "tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
    "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "winner_hand",
    "winner_ht", "winner_ioc", "winner_age", "winner_rank", "winner_rank_points",
    "loser_id", "loser_seed", "loser_entry", "loser_name", "loser_hand", "loser_ht",
    "loser_ioc", "loser_age", "loser_rank", "loser_rank_points", "score", "best_of",
    "round", "minutes",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]


def load_all_tml_matches(extra_files=None):
    paths = sorted(glob.glob(str(TML / "[12][0-9][0-9][0-9].csv")))
    paths.append(str(TML / "ongoing_tourneys.csv"))
    if extra_files:
        paths.extend(str(p) for p in extra_files)

    frames = []
    for p in paths:
        df = pd.read_csv(p, encoding="latin-1", low_memory=False)
        for c in YEAR_COLS:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[YEAR_COLS].copy()
        df["_source_file"] = p
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def find_name_inconsistencies(df: pd.DataFrame) -> pd.DataFrame:
    w = df[["winner_id", "winner_name"]].rename(columns={"winner_id": "id", "winner_name": "name"})
    l = df[["loser_id", "loser_name"]].rename(columns={"loser_id": "id", "loser_name": "name"})
    pairs = pd.concat([w, l], ignore_index=True).dropna(subset=["id"])
    counts = pairs.drop_duplicates().groupby("id")["name"].apply(list)
    flagged = counts[counts.map(len) > 1]
    rows = [{"id": idx, "observed_names": " | ".join(sorted(set(names)))} for idx, names in flagged.items()]
    return pd.DataFrame(rows)


def main():
    df = load_all_tml_matches()
    print(f"[i] Loaded {len(df):,} raw match rows from TML-Database ({df['_source_file'].nunique()} files)")

    name_review = find_name_inconsistencies(df)
    name_review_path = REVIEW_DIR / "match_name_inconsistencies.csv"
    name_review.to_csv(name_review_path, index=False)
    print(f"[i] Player IDs with >1 observed name spelling: {len(name_review):,} -> {name_review_path}")

    df["tourney_date"] = parse_yyyymmdd(df["tourney_date"])

    before = len(df)
    df = df.sort_values(["tourney_date", "tourney_id", "match_num"])
    dupe_mask = df.duplicated(subset=["tourney_id", "match_num"], keep="first")
    dupes = df[dupe_mask]
    dupes_path = REVIEW_DIR / "match_duplicates_removed.csv"
    dupes.to_csv(dupes_path, index=False)

    df = df[~dupe_mask].drop(columns=["_source_file"]).reset_index(drop=True)
    print(f"[i] Deduped on (tourney_id, match_num): {before:,} -> {len(df):,} rows "
          f"({dupe_mask.sum():,} duplicates removed -> {dupes_path})")

    master_path = MASTER_DIR / "matches_master.csv"
    df.to_csv(master_path, index=False)
    print(f"[OK] matches_master.csv written -> {master_path}")


if __name__ == "__main__":
    main()

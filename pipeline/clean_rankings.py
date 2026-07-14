#!/usr/bin/env python3
"""
Phase 1, steps 5-6: dedupe rankings on (player_id, date) - never on name - and
validate every ranking row against the canonical player table, flagging (not
dropping) rows whose player_id doesn't resolve to a canonical id.

Sackmann's atp_rankings_*.csv are keyed by his own numeric player_id, which is
crosswalked to the canonical TML id via build_canonical.py's output.

Outputs:
  data/master/rankings_master.csv            (deduped, canonical_id-tagged where resolvable)
  data/review/rankings_unmatched.csv         (rows whose player_id has no canonical crosswalk)
  data/review/rankings_duplicates_removed.csv
"""
import glob
import pandas as pd

from pipeline.common import JEFF, CANONICAL_DIR, MASTER_DIR, REVIEW_DIR, parse_yyyymmdd


def load_all_rankings():
    paths = sorted(glob.glob(str(JEFF / "atp_rankings_*.csv")))
    frames = [pd.read_csv(p, low_memory=False) for p in paths]
    return pd.concat(frames, ignore_index=True)


def main():
    rankings = load_all_rankings()
    rankings["ranking_date"] = parse_yyyymmdd(rankings["ranking_date"])
    print(f"[i] Loaded {len(rankings):,} raw ranking rows")

    before = len(rankings)
    rankings = rankings.sort_values("ranking_date")
    dupe_mask = rankings.duplicated(subset=["player", "ranking_date"], keep="last")
    dupes_path = REVIEW_DIR / "rankings_duplicates_removed.csv"
    rankings[dupe_mask].to_csv(dupes_path, index=False)
    rankings = rankings[~dupe_mask].reset_index(drop=True)
    print(f"[i] Deduped on (player_id, date): {before:,} -> {len(rankings):,} rows "
          f"({dupe_mask.sum():,} removed -> {dupes_path})")

    canonical = pd.read_csv(CANONICAL_DIR / "canonical_players.csv")
    crosswalk = canonical.dropna(subset=["sackmann_id"])[["id", "sackmann_id"]].copy()
    crosswalk["sackmann_id"] = crosswalk["sackmann_id"].astype("Int64")
    rankings["player"] = rankings["player"].astype("Int64")

    merged = rankings.merge(
        crosswalk.rename(columns={"sackmann_id": "player", "id": "canonical_id"}),
        on="player", how="left"
    )

    unmatched = merged[merged["canonical_id"].isna()]
    unmatched_path = REVIEW_DIR / "rankings_unmatched.csv"
    unmatched.to_csv(unmatched_path, index=False)
    print(f"[i] Rows with no canonical player_id match: {len(unmatched):,} "
          f"({len(unmatched) / len(merged):.1%}) -> {unmatched_path} (flagged, NOT dropped)")

    master_path = MASTER_DIR / "rankings_master.csv"
    merged.to_csv(master_path, index=False)
    print(f"[OK] rankings_master.csv written -> {master_path}  ({len(merged):,} rows total)")


if __name__ == "__main__":
    main()

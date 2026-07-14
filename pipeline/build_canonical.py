#!/usr/bin/env python3
"""
Phase 1, steps 2-3: build the canonical player ID lookup table.

Canonical ID space = TML-Database's own `id` field (TML-Database/ATP_Database.csv).
This is what winner_id/loser_id already carry in every TML-sourced match file
(TML-Database/*.csv, ongoing_tourneys.csv, 2026.csv) - used directly, no matching needed.

Sackmann's tennis_atp uses a *different* numeric player_id namespace (atp_players.csv),
which only shows up in this project via the ranking time-series files
(atp_rankings_*.csv have no TML-style id). To bring rankings into the canonical
ID space we build a one-time crosswalk: Sackmann player_id -> canonical TML id,
matched on (normalized name + date of birth) first, falling back to fuzzy name
matching (rapidfuzz) when dob is missing/absent on either side. Ambiguous or
low-confidence matches are written to a review file, never auto-merged.

Outputs:
  data/canonical/canonical_players.csv       (id, player, dob, ioc, hand, sackmann_player_id)
  data/review/player_crosswalk_review.csv    (flagged / ambiguous / unmatched crosswalk rows)
"""
import pandas as pd
from rapidfuzz import fuzz, process

from pipeline.common import TML, JEFF, CANONICAL_DIR, REVIEW_DIR, normalize_name

FUZZY_ACCEPT_THRESHOLD = 92   # auto-accept fuzzy match only when no dob and score >= this
FUZZY_REVIEW_THRESHOLD = 80   # below this, don't even bother flagging - too weak to be useful


def load_tml_players():
    df = pd.read_csv(TML / "ATP_Database.csv", encoding="latin-1")
    df = df.rename(columns={"id": "canonical_id", "player": "player_name"})
    df["dob"] = pd.to_datetime(df["birthdate"].astype(str), format="%Y%m%d", errors="coerce")
    df["_key"] = df["player_name"].map(normalize_name)
    return df[["canonical_id", "player_name", "dob", "ioc", "hand", "_key"]]


def load_sackmann_players():
    df = pd.read_csv(JEFF / "atp_players.csv")
    df["player_name"] = (df["name_first"].fillna("") + " " + df["name_last"].fillna("")).str.strip()
    df["dob"] = pd.to_datetime(df["dob"].astype(str), format="%Y%m%d", errors="coerce")
    df["_key"] = df["player_name"].map(normalize_name)
    return df.rename(columns={"player_id": "sackmann_id"})[
        ["sackmann_id", "player_name", "dob", "ioc", "_key"]
    ]


def build_crosswalk(tml, sackmann):
    tml_by_key = {}
    for _, r in tml.iterrows():
        tml_by_key.setdefault(r["_key"], []).append(r)

    tml_keys = list(tml_by_key.keys())

    matches, review = [], []
    for _, s in sackmann.iterrows():
        candidates = tml_by_key.get(s["_key"], [])

        if len(candidates) == 1:
            t = candidates[0]
            # exact normalized-name match; confirm with dob when both present
            if pd.notna(s["dob"]) and pd.notna(t["dob"]) and s["dob"] != t["dob"]:
                review.append({
                    "sackmann_id": s["sackmann_id"], "sackmann_name": s["player_name"],
                    "sackmann_dob": s["dob"], "candidate_canonical_id": t["canonical_id"],
                    "candidate_name": t["player_name"], "candidate_dob": t["dob"],
                    "match_score": 100, "reason": "name matched exactly but dob conflicts",
                })
                continue
            matches.append({"sackmann_id": s["sackmann_id"], "canonical_id": t["canonical_id"],
                             "match_score": 100, "method": "exact_name"})
            continue

        if len(candidates) > 1:
            # same normalized name shared by multiple canonical players - disambiguate by dob
            dob_hits = [t for t in candidates if pd.notna(s["dob"]) and pd.notna(t["dob"]) and s["dob"] == t["dob"]]
            if len(dob_hits) == 1:
                matches.append({"sackmann_id": s["sackmann_id"], "canonical_id": dob_hits[0]["canonical_id"],
                                 "match_score": 100, "method": "exact_name+dob_disambiguated"})
            else:
                for t in candidates:
                    review.append({
                        "sackmann_id": s["sackmann_id"], "sackmann_name": s["player_name"],
                        "sackmann_dob": s["dob"], "candidate_canonical_id": t["canonical_id"],
                        "candidate_name": t["player_name"], "candidate_dob": t["dob"],
                        "match_score": 100, "reason": "ambiguous: multiple canonical players share this name",
                    })
            continue

        # no exact key match at all - fuzzy fallback
        best = process.extract(s["_key"], tml_keys, scorer=fuzz.token_sort_ratio, limit=3)
        if not best or best[0][1] < FUZZY_REVIEW_THRESHOLD:
            review.append({
                "sackmann_id": s["sackmann_id"], "sackmann_name": s["player_name"],
                "sackmann_dob": s["dob"], "candidate_canonical_id": None,
                "candidate_name": None, "candidate_dob": None,
                "match_score": best[0][1] if best else 0, "reason": "no plausible canonical match found",
            })
            continue

        top_key, top_score, _ = best[0]
        top_candidates = tml_by_key[top_key]
        if top_score >= FUZZY_ACCEPT_THRESHOLD and len(top_candidates) == 1 and \
           (pd.isna(s["dob"]) or pd.isna(top_candidates[0]["dob"])):
            # only auto-accept a *fuzzy* (non-exact) match when dob can't contradict it
            t = top_candidates[0]
            matches.append({"sackmann_id": s["sackmann_id"], "canonical_id": t["canonical_id"],
                             "match_score": top_score, "method": "fuzzy_name"})
        else:
            for key, score, _ in best:
                for t in tml_by_key[key]:
                    review.append({
                        "sackmann_id": s["sackmann_id"], "sackmann_name": s["player_name"],
                        "sackmann_dob": s["dob"], "candidate_canonical_id": t["canonical_id"],
                        "candidate_name": t["player_name"], "candidate_dob": t["dob"],
                        "match_score": score, "reason": "fuzzy match below auto-accept confidence",
                    })

    return pd.DataFrame(matches), pd.DataFrame(review)


def main():
    tml = load_tml_players()
    sackmann = load_sackmann_players()

    match_df, review_df = build_crosswalk(tml, sackmann)

    canonical = tml.drop(columns=["_key"]).rename(columns={"canonical_id": "id", "player_name": "player"})
    canonical = canonical.merge(
        match_df.rename(columns={"canonical_id": "id"})[["id", "sackmann_id"]],
        on="id", how="left"
    )
    # a canonical player can only carry one sackmann_id crosswalk; keep first, drop exact dupes
    canonical = canonical.drop_duplicates(subset=["id"])

    canonical_path = CANONICAL_DIR / "canonical_players.csv"
    review_path = REVIEW_DIR / "player_crosswalk_review.csv"
    canonical.to_csv(canonical_path, index=False)
    review_df.to_csv(review_path, index=False)

    print(f"[i] TML canonical players:        {len(tml):,}")
    print(f"[i] Sackmann players:              {len(sackmann):,}")
    print(f"[i] Crosswalked (exact + fuzzy):   {len(match_df):,}")
    print(f"[i] Flagged for manual review:     {len(review_df):,}  -> {review_path}")
    print(f"[OK] canonical_players.csv written -> {canonical_path}")


if __name__ == "__main__":
    main()

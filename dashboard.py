# dashboard.py - Predictions + verification-chain dashboard (Streamlit)
#
# Run with: .venv\Scripts\streamlit.exe run dashboard.py
#
# Shows: upcoming/pending predictions, resolved accuracy (walk-forward vs
# same-day, never blended), and the full audit trail for each day's batch -
# SHA-256 hash, OpenTimestamps Bitcoin-confirmation status, and the local git
# commit it was recorded in. See "How verification works" at the bottom for
# the plain-English explanation of the whole chain.

import json
import subprocess
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline.common import CANONICAL_DIR, ROOT
from pipeline.db import get_connection
from pipeline.ots_stamp import check_and_upgrade

st.set_page_config(page_title="tennispredictor.io - Predictions & Verification", page_icon="🎾", layout="wide")

LOGS_DIR = ROOT / "logs"
PREDICTIONS_DIR = ROOT / "data" / "predictions"
SCAN_LOG_PATH = LOGS_DIR / "scan_log.jsonl"


@st.cache_data(ttl=60)
def load_names():
    return pd.read_csv(CANONICAL_DIR / "canonical_players.csv")[["id", "player"]].set_index("id")["player"]


@st.cache_data(ttl=60)
def load_predictions():
    # get_connection() runs CREATE TABLE IF NOT EXISTS for both tables - a bare
    # sqlite3.connect() would "succeed" against a brand-new/empty DB file but then
    # crash on this query with "no such table: predictions" (seen on a fresh
    # deploy where daily_scan hadn't run yet) instead of falling through to the
    # empty-state message below.
    conn = get_connection()
    df = pd.read_sql_query(
        """
        SELECT p.created_at, p.match_date, p.player_a_id, p.player_b_id,
               p.predicted_winner_id, p.predicted_prob_a, p.prediction_type,
               r.actual_winner_id
        FROM predictions p
        LEFT JOIN results r
          ON p.match_date = r.match_date AND p.player_a_id = r.player_a_id AND p.player_b_id = r.player_b_id
        ORDER BY p.created_at DESC
        """,
        conn,
    )
    conn.close()
    return df


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    names = load_names()
    df = df.copy()
    df["player_a"] = df["player_a_id"].map(names).fillna(df["player_a_id"])
    df["player_b"] = df["player_b_id"].map(names).fillna(df["player_b_id"])
    df["favorite"] = df.apply(
        lambda r: r["player_a"] if r["predicted_winner_id"] == r["player_a_id"] else r["player_b"], axis=1
    )
    df["confidence"] = df.apply(
        lambda r: r["predicted_prob_a"] if r["predicted_winner_id"] == r["player_a_id"] else 1 - r["predicted_prob_a"],
        axis=1,
    )
    df["outcome"] = df.apply(
        lambda r: "pending" if pd.isna(r["actual_winner_id"])
        else ("correct" if r["predicted_winner_id"] == r["actual_winner_id"] else "wrong"),
        axis=1,
    )
    return df


@st.cache_data(ttl=300)
def load_scan_log():
    if not SCAN_LOG_PATH.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in SCAN_LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def git_commit_for_date(date_str: str):
    result = subprocess.run(
        ["git", "log", "--all", f"--grep=Daily scan {date_str}", "--format=%H %s"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    return lines[-1].split(" ", 1)[0] if lines else None


title_col, nav_col = st.columns([5, 1])
with title_col:
    st.title("🎾 tennispredictor.io - Predictions & Verification")
with nav_col:
    st.write("")
    if st.button("🎾 Predictor", width="stretch"):
        st.switch_page("app.py")

preds = load_predictions()
if preds.empty:
    st.info("No predictions logged yet. Run `python -m pipeline.daily_scan` at least once.")
    st.stop()

preds = annotate(preds)

tab_upcoming, tab_history, tab_verify, tab_about = st.tabs(
    ["📅 Upcoming", "📊 History & Accuracy", "🔒 Verification Chain", "ℹ️ How this works"]
)

with tab_upcoming:
    pending = preds[preds["outcome"] == "pending"].sort_values("match_date")
    st.subheader(f"{len(pending)} pending prediction(s)")
    if pending.empty:
        st.write("No unplayed matches predicted right now.")
    else:
        st.dataframe(
            pending[["match_date", "player_a", "player_b", "favorite", "confidence", "prediction_type"]]
            .rename(columns={"prediction_type": "type"}),
            width="stretch", hide_index=True,
        )
        st.caption(
            "`true_forward` = predicted before this match existed in any results feed (genuine walk-forward). "
            "`same_day_fast_turnaround` = predicted the moment a completed match first appeared in our data - "
            "informational only, never counted as walk-forward accuracy."
        )

with tab_history:
    resolved = preds[preds["outcome"] != "pending"]
    st.subheader("Accuracy by prediction type (never blended)")
    for ptype in ["true_forward", "same_day_fast_turnaround"]:
        sub = resolved[resolved["prediction_type"] == ptype]
        col1, col2, col3 = st.columns(3)
        col1.metric(f"{ptype} - n resolved", len(sub))
        if len(sub):
            acc = (sub["outcome"] == "correct").mean()
            col2.metric("model accuracy", f"{acc:.1%}")
        else:
            col2.metric("model accuracy", "—")
        col3.metric("still pending", int((preds["prediction_type"] == ptype).sum() - len(sub)))
        st.divider()

    st.subheader("All resolved predictions")
    st.dataframe(
        resolved[["match_date", "player_a", "player_b", "favorite", "confidence", "prediction_type", "outcome"]]
        .sort_values("match_date", ascending=False),
        width="stretch", hide_index=True,
    )

with tab_verify:
    st.subheader("Daily audit trail")
    st.caption(
        "Each morning's run: predictions inserted with a SQLite server-side timestamp -> "
        "exported to JSON -> SHA-256 hashed -> submitted to 4 independent OpenTimestamps calendar "
        "servers -> committed to git locally. Click 'Check Bitcoin confirmation' to ask the calendars "
        "whether a proof has been mined into a Bitcoin block yet (usually takes hours, not minutes)."
    )
    scan_log = load_scan_log()
    if scan_log.empty:
        st.write("No scan log entries yet.")
    else:
        # Bucket by local calendar date, not UTC run time - the 1am and 11:59pm
        # runs for the same local day land on different UTC dates (11:59pm CDT
        # is ~5am UTC the next day), which would otherwise split one day's
        # audit trail across two expanders.
        scan_log["date"] = (
            pd.to_datetime(scan_log["run_started_utc"], utc=True)
            .dt.tz_convert("America/Chicago")
            .dt.strftime("%Y-%m-%d")
        )
        # Two runs a day can share a local date now (1am predicts, 11:59pm just
        # reconciles). Prefer the run that actually logged a predictions batch
        # (has a sha256/ots proof) over a later run that didn't, rather than
        # blindly taking whichever ran last.
        has_sha = "predictions_batch_sha256" in scan_log.columns
        daily_rows = []
        for date_str, g in scan_log.sort_values("run_started_utc").groupby("date"):
            with_sha = g[g["predictions_batch_sha256"].notna()] if has_sha else g.iloc[0:0]
            daily_rows.append(with_sha.iloc[-1] if len(with_sha) else g.iloc[-1])

        for row in sorted(daily_rows, key=lambda r: r["date"], reverse=True):
            date_str = row["date"]
            with st.expander(f"{date_str}", expanded=(date_str == scan_log["date"].max())):
                sha = row.get("predictions_batch_sha256")
                sha = None if pd.isna(sha) else sha
                ots_path_str = row.get("ots_proof")
                ots_path_str = None if pd.isna(ots_path_str) else ots_path_str
                commit = git_commit_for_date(date_str)

                st.write(f"**SHA-256 of prediction batch:** `{sha or 'no predictions logged that day'}`")
                st.write(f"**Local git commit:** `{commit or 'not found'}`")
                if ots_path_str:
                    # Resolve against THIS machine's predictions dir, not the raw stored path -
                    # ots_proof is recorded as an absolute path at scan time, so an entry made on
                    # a different machine/OS (e.g. Windows history migrated onto a Linux deploy)
                    # would otherwise point nowhere even though the file exists right here.
                    # Normalize backslashes -> forward slashes FIRST: a Windows-style path like
                    # "C:\...\x.ots" has no "/" at all, so on Linux (where Path only splits on
                    # "/") .name would return the whole garbled string, not just the filename.
                    proof_filename = ots_path_str.replace("\\", "/").rsplit("/", 1)[-1]
                    ots_path = PREDICTIONS_DIR / proof_filename
                    st.write(f"**.ots proof file:** `{ots_path.name}`")
                    if st.button("Check Bitcoin confirmation", key=f"check_{date_str}"):
                        if ots_path.exists():
                            with st.spinner("Asking calendar servers..."):
                                status = check_and_upgrade(ots_path)
                            if status["confirmed_heights"]:
                                st.success(f"Confirmed in Bitcoin block(s): {status['confirmed_heights']}")
                            else:
                                st.warning(
                                    f"Not confirmed yet - still pending at {len(status['pending_calendars'])} "
                                    f"calendar server(s). This is normal for the first several hours."
                                )
                        else:
                            st.error("Proof file not found locally.")
                else:
                    st.write("No .ots proof for this day (no predictions were generated).")

with tab_about:
    st.markdown(Path(__file__).with_name("VERIFICATION.md").read_text(encoding="utf-8"))

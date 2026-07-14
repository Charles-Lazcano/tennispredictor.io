#!/usr/bin/env python3
"""
Phase 4 steps 19-20 (+ true-forward extension): SQLite schema for
predictions + results.

Design choices:
  - `created_at` / `recorded_at` are SQLite CURRENT_TIMESTAMP defaults - set
    by SQLite itself at insert time, never passed in by application code, so
    there's no manually-typed date anywhere in this path.
  - Results are a SEPARATE, insert-only table, joined back to predictions at
    query time. The predictions row is never updated after creation.
  - Predictions are keyed by (match_date, player_a_id, player_b_id) -
    canonical player IDs, not (tourney_id, match_num). A true_forward
    prediction is made from the schedule API BEFORE the match has a TML
    tourney_id/match_num assigned at all, so tourney_id/match_num are
    nullable and only filled in once known (same_day_fast_turnaround
    predictions always know them immediately, since they come from the
    already-completed TML feed). This lets a later completed-match row
    (which does have tourney_id/match_num) be reconciled back to an earlier
    true_forward prediction purely by date + player pair - see
    pipeline/schedule.py's reconcile step.
  - `prediction_type`: 'true_forward' (made before the match existed in any
    feed - via pipeline/schedule.py's upcoming-fixtures pull) vs
    'same_day_fast_turnaround' (made the moment a completed match first
    appears in TennisMyLife's feed). Phase 5's accuracy report only ever
    counts 'true_forward' rows as walk-forward - see pipeline/report.py.
"""
import sqlite3

from pipeline.common import ROOT

DB_PATH = ROOT / "predictions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_date TEXT NOT NULL,
    player_a_id TEXT NOT NULL,
    player_b_id TEXT NOT NULL,
    tourney_id TEXT,
    match_num INTEGER,
    source_fixture_id TEXT,
    predicted_winner_id TEXT NOT NULL,
    predicted_prob_a REAL NOT NULL,
    model_version TEXT NOT NULL,
    prediction_type TEXT NOT NULL CHECK (prediction_type IN ('true_forward', 'same_day_fast_turnaround')),
    features_snapshot TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (match_date, player_a_id, player_b_id)
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_date TEXT NOT NULL,
    player_a_id TEXT NOT NULL,
    player_b_id TEXT NOT NULL,
    tourney_id TEXT,
    match_num INTEGER,
    actual_winner_id TEXT NOT NULL,
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Without this, a race between two overlapping daily_scan runs (or a rerun of
-- reconcile_results over the same newly-completed match) can insert the same
-- match twice, double-counting it in the dashboard's accuracy metrics.
CREATE UNIQUE INDEX IF NOT EXISTS idx_results_unique
    ON results (match_date, player_a_id, player_b_id);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def insert_prediction(conn, *, match_date, player_a_id, player_b_id, predicted_winner_id,
                       predicted_prob_a, model_version, prediction_type, features_snapshot_json,
                       tourney_id=None, match_num=None, source_fixture_id=None) -> bool:
    """Insert-only. created_at is never passed in - SQLite stamps it server-side.

    Returns True only if a new row was actually inserted (rowcount==1) - OR IGNORE
    means a duplicate (match_date, player_a_id, player_b_id) silently no-ops, so
    callers must check this before counting the prediction as "logged"."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO predictions
           (match_date, player_a_id, player_b_id, tourney_id, match_num, source_fixture_id,
            predicted_winner_id, predicted_prob_a, model_version, prediction_type, features_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (match_date, player_a_id, player_b_id, tourney_id, match_num, source_fixture_id,
         predicted_winner_id, predicted_prob_a, model_version, prediction_type, features_snapshot_json),
    )
    return cur.rowcount == 1


def insert_result(conn, *, match_date, player_a_id, player_b_id, actual_winner_id,
                   tourney_id=None, match_num=None) -> bool:
    """Insert-only, separate table - never touches the predictions row.

    Returns True only if a new row was actually inserted; OR IGNORE + the unique
    index on (match_date, player_a_id, player_b_id) means a duplicate reconciliation
    (e.g. from a racing concurrent scan) silently no-ops instead of double-counting."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO results (match_date, player_a_id, player_b_id, tourney_id, match_num, actual_winner_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (match_date, player_a_id, player_b_id, tourney_id, match_num, actual_winner_id),
    )
    return cur.rowcount == 1

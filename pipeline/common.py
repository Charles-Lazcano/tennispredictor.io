"""Shared helpers for the cleaning/merge pipeline."""
import os
import re
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TML = ROOT / "TML-Database"
JEFF = ROOT / "tennis_atp"

CANONICAL_DIR = DATA / "canonical"
REVIEW_DIR = DATA / "review"
MASTER_DIR = DATA / "master"
LOGS_DIR = ROOT / "logs"
for d in (CANONICAL_DIR, REVIEW_DIR, MASTER_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)


class AlreadyRunningError(RuntimeError):
    """Raised when a named lock is already held - see run_lock()."""


@contextmanager
def run_lock(name: str, stale_after_seconds: int = 7200):
    """Refuse to start a second, overlapping run of the same pipeline step.

    Two concurrent `daily_scan` invocations racing the same SQLite DB/CSVs is
    exactly what produced duplicate scan_log.jsonl entries for one logical run
    (identical run_started_utc, inconsistent true_forward counters - the
    "loser" of the race reads state before the "winner" commits its work and
    logs zeros even though the work happened). A lock file, not just an
    in-process guard, is required since each run is a separate OS process.
    """
    lock_path = LOGS_DIR / f"{name}.lock"
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age < stale_after_seconds:
            raise AlreadyRunningError(
                f"'{name}' is already running (lock age {age:.0f}s) - refusing to start an "
                f"overlapping instance. If you're certain no run is active, delete {lock_path}."
            )
        # Stale lock (older than stale_after_seconds) - previous run almost certainly crashed
        # without cleaning up. Safe to reclaim rather than block forever.
    lock_path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)

ATP_LEVELS_250_PLUS = {"G", "M", "F", "A"}  # Grand Slam, Masters1000, Tour Finals, ATP-tour (250/500)
# TML/Sackmann tourney_level: 'G'=Slam, 'M'=Masters1000, 'F'=Finals, 'A'=other tour-level (250/500),
# 'C'=Challenger, 'S'=satellite/ITF, 'D'=Davis Cup. We keep G/M/F/A as "ATP 250+", everything else
# (Challenger and below) goes to the secondary table.


def normalize_name(name) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace - for fuzzy/exact name matching."""
    if name is None:
        return ""
    s = str(name)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_yyyymmdd(series):
    import pandas as pd
    return pd.to_datetime(series.astype("Int64").astype(str), format="%Y%m%d", errors="coerce")


def retrying_session(total_retries: int = 3, backoff_factor: float = 1.0) -> requests.Session:
    """A requests.Session that retries transient failures - connection errors,
    read timeouts, and 429/5xx responses - with exponential backoff (roughly
    1s, 2s, 4s between attempts with the defaults below). Does NOT retry other
    4xx responses (bad request, auth, not found) since those won't succeed on
    a retry - those still raise immediately via the caller's raise_for_status().

    Used by pipeline/fetch.py (TennisMyLife) and pipeline/schedule.py
    (RapidAPI) - both previously used bare requests.get() with zero retry, so
    a single transient network blip failed an entire scheduled scan and had
    to wait for the next one to recover.
    """
    retry = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=True,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

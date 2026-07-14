# tennispredictor.io

### ATP match-outcome, total-games, and match-length prediction — with a verifiable, tamper-evident audit trail

**[Live app → tennispredictor.io](https://tennispredictor.io)**

---

<img width="962" alt="Predictor UI — live win probability, set count, and total games estimate" src="https://github.com/user-attachments/assets/95439932-5211-4d9d-a8f1-6dd1e17d03ee" />

Pick two players, a surface, and a match format — get a live win-probability estimate, a set-count breakdown, and a total-games estimate with an over/under helper.

---

<img width="1808" alt="Verification Dashboard — accuracy history and blockchain-anchored audit trail" src="https://github.com/user-attachments/assets/0f214d71-26aa-4b8e-8fb9-46f725f0b6c7" />

Every prediction is timestamped at insert time, SHA-256 hashed, and anchored to the Bitcoin blockchain via **OpenTimestamps** — so the model's track record isn't just a claim, it's checkable.

---

<p align="center">
  <img width="45%" src="docs/notebook_example.png" alt="Exploratory notebook — feature relevance analysis" />
  <img width="45%" src="docs/notebook_example2.png" alt="Exploratory notebook — prediction error patterns" />
</p>

The project began as exploratory analysis in a Jupyter notebook — testing feature relevance and error patterns — before becoming a modular, production pipeline.

---

## What this is

A Python analytics system that predicts professional tennis outcomes — win probability, total games, and match length (two vs. three sets) — from historical ATP data. It's built around three ideas: a custom rolling-window Elo system, a fully automated daily data pipeline, and a cryptographically verifiable prediction log, all deployed as a live web app.

Modeling follows strict walk-forward validation discipline: no prediction is ever allowed to see information that wouldn't have existed at the time it was made.

## How it works

**Data** — Jeff Sackmann's historical ATP data, a daily completed-match feed, and an upcoming-fixtures feed (for genuine walk-forward predictions made before an outcome exists anywhere). A canonical player-identity system resolves the same player across data sources that use different ID schemes, flagging anything ambiguous for manual review instead of guessing.

**Features** — rolling 3-year-window Elo (global + surface-specific), recomputed walk-forward so a rating only ever reflects the trailing window, never a whole career or the future; recent-form (trailing win rate); ranking differentials, age, and match-format indicators.

**Models** — logistic regression for win probability; gradient-boosted models for total games and match length, each trained and evaluated on its own feature pipeline.

**Verification** — predictions are split into `true-forward` (predicted before the match existed in any results feed — genuine walk-forward accuracy) and `same-day` (predicted the moment a result appeared — informational only). The two are never blended in accuracy reporting.

**Pipeline** — runs unattended multiple times a day: fetch new results → reconcile prior true-forward predictions against outcomes → pull upcoming fixtures and generate new predictions → hash and log the run → commit the day's data.

**Deployment** — AWS EC2, Nginx + Let's Encrypt over HTTPS, systemd for auto-restart, a Streamlit front end, and a cron-scheduled pipeline.

## Known limitations

Not modeled: **injury status**, **jet lag / travel schedule**, and **fatigue** (recent match load). These are documented gaps, not silent errors — weight predictions accordingly.

## Data sources

Jeff Sackmann's Tennis Data, a daily completed-match feed, and an upcoming-fixtures feed. Raw and derived data tables are handled locally/server-side and excluded from version control.

## Repository scope

This repo includes the modeling (`train*.py`), verification/audit-trail (`pipeline/db.py`, `pipeline/ots_stamp.py`, `pipeline/report.py`), data-cleaning (`pipeline/build_canonical.py`, `clean_matches.py`, `clean_rankings.py`), Elo (`pipeline/elo.py`), dashboard, and deployment layers. The modules that talk directly to third-party data providers (fetch/scheduling scripts) are kept in a private companion repo, since publishing exact scraping/API-access patterns against services with restrictive terms isn't something I want in a public index. Happy to walk through the full pipeline live.

## Development note

AI coding assistants (ChatGPT and Claude) were used as supplementary tools for brainstorming, code structuring, documentation drafting, and deployment troubleshooting. All modeling decisions, data handling, evaluation logic, and system architecture were designed and validated by me (Charles).

## Disclaimer

For educational and analytical purposes, demonstrating applied machine learning and systems engineering in a sports analytics context. Tennis databases, files, and algorithms by Jeff Sackmann / Tennis Abstract.

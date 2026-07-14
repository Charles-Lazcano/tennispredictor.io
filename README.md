# Tennis Match Analytics & Prediction System

**Live app: [tennispredictor.io](https://tennispredictor.io)**

## Project Overview
This project is a Python-based analytics system that predicts professional tennis match outcomes — win probability, total games, and match length (two sets vs. three sets) — using historical ATP data. It combines a custom rolling-window Elo rating system, an automated daily data pipeline, and a cryptographically verifiable prediction audit trail, deployed as a live web application.

The project emphasizes reproducible modeling, walk-forward validation discipline (never using information that wouldn't have been available at prediction time), and verifiable, tamper-evident record-keeping — treating prediction accuracy as something to be independently checked, not just claimed.

**Development Note:**
AI coding assistants (ChatGPT and Claude) were used as supplementary tools for brainstorming, code structuring, documentation drafting, and deployment troubleshooting during development. All modeling decisions, data handling, evaluation logic, and system architecture were designed and validated by me (Charles).

---

## Exploratory Analysis

The project began with an exploratory data analysis and model validation phase conducted in a Jupyter notebook, investigating feature relevance and prediction error patterns before moving to a modular, production-style pipeline.

![Exploratory Notebook Example](docs/notebook_example2.png)
![Exploratory Notebook Example](docs/notebook_example.png)

---

## Motivation
Match outcomes and match length in tennis are influenced by surface, player skill balance, recent form, and historical performance patterns. This project explores how a rolling, walk-forward Elo system and machine learning models can capture those relationships and produce stable, interpretable forecasts — while holding the modeling process to the same standard a skeptical reader would apply: show your work, and make it checkable.

---

## Data Sources
This project draws on publicly available professional tennis datasets, including:

- **Jeff Sackmann's Tennis Data** — historical ATP match results, rankings, and metadata used for feature engineering and long-term trend analysis.
- **A daily-updated match results feed** — completed-match data used to keep the model current.
- **An upcoming-fixtures feed** — used to generate genuine walk-forward predictions *before* a match's outcome exists in any data source (see "Prediction Verification" below).

Raw datasets and derived training tables are handled locally/server-side and are intentionally excluded from version control.

---

## Data & Feature Engineering
The system computes features including:
- **Rolling 3-year-window Elo ratings** (global and surface-specific), recomputed on a walk-forward basis so a player's rating at any point in time depends only on matches from the trailing window — never their whole career, and never the future
- **Recent-form** (trailing win rate over a player's last several matches)
- Player ranking differentials, age, and match-format indicators
- A canonical player-identity system that resolves the same player across multiple data sources with different ID schemes/name spellings, flagging ambiguous matches for manual review rather than guessing

---

## Modeling Architecture
- **Win probability**: a logistic regression model trained on canonical player IDs and the rolling Elo/form features above
- **Total games & match length (two sets vs. three sets)**: gradient-boosting models trained on a complementary feature set

Each model is trained and evaluated independently, with its own feature pipeline.

---

## Prediction Verification & Audit Trail
Rather than just reporting an accuracy number, every prediction batch is independently verifiable after the fact:

- Predictions are timestamped at insert time by the database itself (never hand-typed)
- Each day's prediction batch is SHA-256 hashed and anchored via **OpenTimestamps**, producing a proof that can later verify the predictions existed at that hash *before* a certain point in time — anchored to the Bitcoin blockchain
- Every daily update is committed to version control, giving a full, inspectable history of the dataset and predictions over time
- Predictions are explicitly split into two categories that are **never blended** in accuracy reporting:
  - *true-forward*: predicted from a schedule feed before the match existed in any completed-results source — genuine walk-forward accuracy
  - *same-day*: predicted the moment a completed match first appeared in the data feed — informational only, not counted as walk-forward accuracy

This means the model's track record isn't just a claim — it's checkable.

---

## Automated Daily Pipeline
The system runs unattended, multiple times a day:
1. Fetch newly completed matches and merge genuinely new rows into the dataset
2. Reconcile any previously-made true-forward predictions against now-known results
3. Pull upcoming fixtures and generate new true-forward predictions
4. Log a structured, hash-verified record of the run
5. Commit the day's dataset and prediction updates

---

## Deployment
The live application is deployed on **AWS EC2** (Amazon Linux), served over HTTPS via **Nginx** with a **Let's Encrypt** certificate, managed by **systemd** for automatic restarts, with the daily pipeline above running on a cron schedule. The application itself is built with **Streamlit**.

---

## Application Interface
The live app has two pages:

- **Predictor** — pick two players, surface, and match format to get a live win-probability estimate, set-count breakdown, and total-games estimate with an over/under helper
- **Verification Dashboard** — pending and resolved predictions, accuracy broken out by prediction type, and the full per-day audit trail described above (hash, blockchain-anchoring status, and commit reference)

![Tennis Match Predictor UI](docs/ui_preview.png)


## Example Prediction Output

![Prediction Output Example]<img width="962" height="814" alt="Screenshot 2026-07-14 163501" src="https://github.com/user-attachments/assets/95439932-5211-4d9d-a8f1-6dd1e17d03ee" />




![Verification Dashboard](<img width="1808" height="815" alt="Screenshot 2026-07-14 161630" src="https://github.com/user-attachments/assets/0f214d71-26aa-4b8e-8fb9-46f725f0b6c7" />

)


- Walk-forward validation discipline — never let a model see information from the future, even accidentally
- Deterministic inference (no subjective overrides)
- Verifiable, not just reported: predictions are hashed and timestamped so accuracy claims can be independently checked
- Clear separation between training, prediction, evaluation, and verification
- "Flag, don't guess" — ambiguous data (e.g. unresolved player identities) is routed to a review file rather than silently assumed
- Modular, experiment-friendly codebase

---

## Known Limitations
This model does **not** account for:
- **Injury status** — a player listed as healthy may be carrying an undisclosed injury that materially changes their win probability
- **Jet lag / travel schedule** — back-to-back tournaments across time zones aren't tracked as a feature
- **Fatigue** — recent match load (sets/minutes played in prior days) isn't currently fed into the model

These are documented gaps, not silent errors — predictions should be weighted accordingly.

---

## Disclaimer
This repository is intended for educational and analytical purposes and demonstrates applied machine learning and systems engineering in a sports analytics context. Tennis databases, files, and algorithms by Jeff Sackmann / Tennis Abstract.

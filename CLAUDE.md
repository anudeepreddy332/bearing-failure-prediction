# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

ML system that predicts Remaining Useful Life (RUL) for bearings using the NASA IMS Bearing Dataset
(raw vibration signals, 20 kHz). Ships a tuned LightGBM regressor (2.88h MAE in the 0-50h critical
zone), a Streamlit monitoring dashboard, and a FastAPI prediction endpoint.

## Environment setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL, etc.
```

There is no test suite, linter, or formatter configured in this repo (no pytest config, no
`.flake8`/`ruff`/`black` config, no CI). `src/data/test.py` is a scratch script, not a real test.
Don't assume `pytest` will find anything to run.

## Database

Postgres is the source of truth for features, labels, and splits (not the parquet files — see
"Two pipeline generations" below). Bring it up with:

```bash
docker-compose up -d          # postgres:15, maps to localhost:5432
psql -f src/db/migrations/001_schema.sql   # tables: raw_data, windows, features, predictions, model_registry, experiments
psql -f src/db/migrations/002_add_temporal_features.sql  # materialized views
```

Every script reads `DATABASE_URL` from the environment but **falls back to a hardcoded default**
of `postgresql://postgres:postgres@localhost:5432/anudeep` (db name `anudeep`) if it's unset. This
default is inconsistent with `docker-compose.yml` (db `ims_bearing`) and the README (db
`bearing_prediction`) — always set `DATABASE_URL` explicitly rather than relying on the fallback,
and expect to hit connection errors from mismatched db names if you don't.

The `features` table (see `001_schema.sql`) is wide and central: one row per
file/timestamp/bearing/axis, with time-domain, frequency-domain, and temporal/engineered feature
columns plus label columns (`rul_hours`, `rul_seconds`, `failed`, `censored`) and a `split` column
added by the splitter scripts.

## Pipeline (order matters)

The production pipeline runs end-to-end against Postgres:

```bash
python src/data/ingest.py --parquet data/processed/set1_features.parquet   # bulk COPY into `features`
python src/data/labeling.py                                                 # compute rul_hours/failed/censored
python src/data/validate.py                                                 # data-quality report -> reports/
python src/data/split_stratified.py --train-pct 0.8                        # adds split='train'/'test' column
python src/features/select_features.py --top-n 50 --method combined        # ranks/writes data/processed/selected_features.csv
python src/models/train.py --model both                                     # baseline RF + LightGBM
python src/models/tune.py --trials 80                                       # Optuna tuning -> models/lightgbm_v2_tuned.pkl
python src/models/evaluate_tuned.py                                         # RUL-range MAE/RMSE/R2 -> reports/evaluation/
python src/models/feature_importance.py                                     # -> reports/feature_importance.{csv,png}
```

Then serve:

```bash
streamlit run src/dashboard/app.py     # http://localhost:8501
python src/api/predict_api.py          # FastAPI on :8000 (POST /predict, GET /health)
```

All of `train.py`, `tune.py`, `evaluate_tuned.py`, `select_features.py` read training/test rows
directly via SQL (`WHERE split='train'`/`'test' AND failed=TRUE`), not from a DataFrame passed
between stages — if a stage upstream doesn't write back to Postgres, downstream stages silently
see stale data.

## Two pipeline generations — don't cross the streams

This repo contains two generations of the same pipeline; know which one a file belongs to before
editing:

- **Notebook/parquet generation** (`notebooks/set1/*.py`, `src/data_loader.py`, `src/preprocess.py`,
  `src/utils.py`, `src/temporal_features.py`, `src/config.py`): the original exploratory pipeline.
  Loads raw IMS ASCII files, windows signals, extracts features, writes parquet files under
  `data/processed/`. `notebooks/set1/*.py` are numbered `.py` files meant to be run as Jupyter
  cells (`# %%`-style), not imported.
- **Production/Postgres generation** (`src/data/*.py`, `src/features/*.py`, `src/models/*.py`,
  `src/dashboard/`, `src/api/`): reads/writes Postgres directly with hardcoded SQL, used by the
  dashboard, API, and current model artifacts in `models/`.

Within the Postgres generation, `src/data/split.py` (time-based split) is the **superseded**
approach — it produced a Test R² of -11.9 due to train/test RUL-distribution mismatch (see
README "Model Optimization Strategy"). `src/data/split_stratified.py` (stratified-by-RUL-bin
split) is the one actually used to produce `models/lightgbm_v2_tuned.pkl`. Don't reintroduce
`split.py`'s approach without understanding why it was replaced.

## Modeling notes

- Training uses a **custom weighted MAE loss** that upweights errors at low RUL
  (`weight = 1 + 1/(y_true + 10)`) because a 30h error at RUL=10h is catastrophic while the same
  error at RUL=500h is negligible. This is why `evaluate_tuned.py` reports MAE broken out by RUL
  range rather than a single aggregate number — the aggregate hides whether the model is actually
  good near failure.
- Failed bearings in Set 1 are bearings 3 and 4 (hardcoded in `src/data/labeling.py`); bearings 1
  and 2 are censored (never failed) and are excluded from RUL-labeled training data.
- `src/config.py` (`SET1_CHANNEL_MAP`, `FS=20000`, `WIN=2048`, `OVERLAP=0.5`) defines the
  windowing constants used by the parquet-generation feature extraction — change these together
  with `src/preprocess.py`'s `window_signal`/`extract_features_from_window`, not independently.
- The API (`src/api/predict_api.py`) and dashboard (`src/dashboard/app.py`) both hardcode the
  model path (`models/lightgbm_v2_tuned.pkl`) and feature list
  (`data/processed/selected_features.csv`) rather than reading `MODEL_PATH`/`FEATURES_PATH` from
  `.env` even though `.env.example` defines them — if you retrain a new model version, update
  these paths in both files (and `evaluate_tuned.py`, `feature_importance.py`) or wire up the env
  vars properly.

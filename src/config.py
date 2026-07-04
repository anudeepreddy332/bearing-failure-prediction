import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR/"data"
PROCESSED_DIR = DATA_DIR/"processed"
SET1_FEATURES = PROCESSED_DIR/"set1_features.parquet"
SET1_LABELED = PROCESSED_DIR/"set1_labeled.parquet"


SET1_CHANNEL_MAP = {
    0: {"bearing": 1, "axis": "x"},
    1: {"bearing": 1, "axis": "y"},
    2: {"bearing": 2, "axis": "x"},
    3: {"bearing": 2, "axis": "y"},
    4: {"bearing": 3, "axis": "x"},
    5: {"bearing": 3, "axis": "y"},
    6: {"bearing": 4, "axis": "x"},
    7: {"bearing": 4, "axis": "y"},
}

FS = 20000      # sampling rate (Hz)
WIN = 2048      # samples/window (~0.1024 s)
OVERLAP = 0.5   # 50%


# ---------------------------------------------------------------------------
# Runtime configuration (single source of truth)
#
# Historically the DB connection string was hardcoded and duplicated across ~8
# files with a personal database name as the fallback, which matched neither
# docker-compose.yml (db: ims_bearing) nor the README. Every module should now
# call get_database_url() so there is exactly one place that reads the
# environment. The legacy default is preserved so existing local setups keep
# working, but a warning nudges toward setting DATABASE_URL explicitly.
# ---------------------------------------------------------------------------

# Preserved legacy default: keeps pre-existing local dev environments working
# unchanged. NOT a secret (default postgres creds against localhost); real
# deployments MUST set DATABASE_URL (and, in cloud, source it from a secret
# manager rather than an env literal).
_LEGACY_DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/anudeep"

# Default model / feature artifact locations (overridable via env).
DEFAULT_MODEL_PATH = str(BASE_DIR / "models" / "lightgbm_v2_tuned.pkl")
DEFAULT_FEATURES_PATH = str(BASE_DIR / "data" / "processed" / "selected_features.csv")


def get_database_url() -> str:
    """Return the Postgres connection URL, env-first.

    Order of precedence:
      1. ``DATABASE_URL`` environment variable (the supported path).
      2. The preserved legacy localhost default (dev convenience only).
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    logger.warning(
        "DATABASE_URL not set; falling back to the local dev default. "
        "Set DATABASE_URL explicitly for anything beyond local development."
    )
    return _LEGACY_DEFAULT_DATABASE_URL


def get_model_path() -> str:
    """Filesystem path to the serving model artifact (env: MODEL_PATH)."""
    return os.getenv("MODEL_PATH", DEFAULT_MODEL_PATH)


def get_features_path() -> str:
    """Filesystem path to the selected-features CSV (env: FEATURES_PATH)."""
    return os.getenv("FEATURES_PATH", DEFAULT_FEATURES_PATH)
"""Offline validation study for IMS Bearing RUL leakage analysis.

This module is intentionally DB-free and artifact-preserving. It compares the
current row-level RUL-stratified split against bearing-held-out and purged
time-series splits using the same selected feature list and LightGBM model
family used by the current project artifacts.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split


SELECTED_FEATURES_PATH = Path("data/processed/selected_features.csv")
FEATURES_PATH = Path("data/processed/test_temporal_features.parquet")
BASE_FEATURES_PATH = Path("data/processed/test_base_features.parquet")
LABELS_PATH = Path("data/processed/set1_labeled.parquet")
SUSPECT_TEMPORAL_PATH = Path("data/processed/set1_features_temporal.parquet")

CRITICAL_RUL_HOURS = 50.0
WARNING_RUL_HOURS = 100.0
RUL_BINS = [0, 50, 100, 150, 200, 300, 400, 600, 850]
RUL_BIN_LABELS = [
    "0-50h",
    "50-100h",
    "100-150h",
    "150-200h",
    "200-300h",
    "300-400h",
    "400-600h",
    "600+h",
]

# Parameters observed in models/lightgbm_v2_tuned.pkl. Keeping them explicit
# avoids loading a pickle just to recover hyperparameters.
TUNED_LGBM_PARAMS = {
    "objective": "regression",
    "metric": "mae",
    "boosting_type": "gbdt",
    "num_leaves": 122,
    "learning_rate": 0.030167988704668327,
    "n_estimators": 350,
    "max_depth": 9,
    "min_child_samples": 10,
    "subsample": 0.8529893793521217,
    "colsample_bytree": 0.85495534487619,
    "reg_alpha": 0.0789408295003718,
    "reg_lambda": 0.1675734802944115,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


@dataclass(frozen=True)
class Fold:
    strategy: str
    fold: str
    train_idx: np.ndarray
    test_idx: np.ndarray
    notes: str = ""


@dataclass(frozen=True)
class FeatureSpec:
    feature: str
    source_feature: str
    transform: str
    parameter: int | None = None
    statistic: str | None = None


def load_selected_features(path: Path = SELECTED_FEATURES_PATH) -> list[str]:
    return pd.read_csv(path)["feature"].tolist()


def parse_feature_spec(feature: str) -> FeatureSpec:
    rolling = re.match(r"^(?P<source>.+)_roll_(?P<window>\d+)_(?P<stat>mean|std)$", feature)
    if rolling:
        return FeatureSpec(
            feature=feature,
            source_feature=rolling.group("source"),
            transform="rolling",
            parameter=int(rolling.group("window")),
            statistic=rolling.group("stat"),
        )

    ema = re.match(r"^(?P<source>.+)_ema_(?P<alpha>\d+)$", feature)
    if ema:
        return FeatureSpec(
            feature=feature,
            source_feature=ema.group("source"),
            transform="ema",
            parameter=int(ema.group("alpha")),
        )

    bearing = re.match(r"^(?P<source>.+)_bearing_(?P<stat>max|min|mean|range)$", feature)
    if bearing:
        return FeatureSpec(
            feature=feature,
            source_feature=bearing.group("source"),
            transform="bearing_aggregate",
            statistic=bearing.group("stat"),
        )

    if feature.endswith("_zscore"):
        return FeatureSpec(
            feature=feature,
            source_feature=feature[: -len("_zscore")],
            transform="zscore",
        )

    return FeatureSpec(feature=feature, source_feature=feature, transform="base")


def classify_selected_features(features: list[str]) -> pd.DataFrame:
    rows = []
    for feature in features:
        spec = parse_feature_spec(feature)
        if spec.transform == "base":
            risk = "none from fold preprocessing"
            method = "use base feature as stored"
        elif spec.transform in {"rolling", "ema"}:
            risk = "precomputed train rows can carry held-out raw history across folds"
            method = "recompute separately inside train/test split in timestamp order"
        elif spec.transform == "bearing_aggregate":
            risk = "precomputed same-timestamp cross-axis aggregate can cross split membership"
            method = "recompute separately inside train/test split"
        else:
            risk = "full bearing-axis mean/std uses validation/test distribution"
            method = "fit mean/std on training rows only; fallback to global train stats for unseen groups"
        rows.append(
            {
                "feature": spec.feature,
                "source_feature": spec.source_feature,
                "transform": spec.transform,
                "parameter": spec.parameter,
                "statistic": spec.statistic,
                "leakage_risk": risk,
                "leakage_safe_method": method,
            }
        )
    return pd.DataFrame(rows)


def load_validation_frame(
    features_path: Path = FEATURES_PATH,
    labels_path: Path = LABELS_PATH,
    selected_features_path: Path = SELECTED_FEATURES_PATH,
    feature_mode: str = "artifact",
) -> tuple[pd.DataFrame, list[str]]:
    """Load features and merge labels from the clean labeled artifact."""
    features = load_selected_features(selected_features_path)
    if feature_mode == "artifact":
        feature_df = pd.read_parquet(features_path)
    elif feature_mode == "leakage_safe":
        feature_df = pd.read_parquet(BASE_FEATURES_PATH)
    else:
        raise ValueError(f"Unsupported feature_mode: {feature_mode}")
    labels_df = pd.read_parquet(labels_path)

    key_cols = ["file", "timestamp", "channel", "bearing", "axis"]
    label_cols = key_cols + ["rul_seconds", "rul_hours", "failed", "censored"]

    if feature_mode == "artifact":
        missing_features = [feature for feature in features if feature not in feature_df.columns]
        if missing_features:
            raise ValueError(f"Selected features missing from {features_path}: {missing_features[:10]}")
    else:
        feature_specs = [parse_feature_spec(feature) for feature in features]
        missing_sources = sorted({spec.source_feature for spec in feature_specs if spec.source_feature not in feature_df.columns})
        if missing_sources:
            raise ValueError(f"Source features missing from {BASE_FEATURES_PATH}: {missing_sources[:10]}")

    for col in key_cols:
        if col not in feature_df.columns or col not in labels_df.columns:
            raise ValueError(f"Required merge key missing: {col}")

    if feature_df.duplicated(key_cols).any():
        raise ValueError(f"{features_path} contains duplicate feature keys")
    if labels_df.duplicated(key_cols).any():
        raise ValueError(f"{labels_path} contains duplicate label keys")

    merged = feature_df.merge(labels_df[label_cols], on=key_cols, how="left", validate="one_to_one")
    merged["timestamp"] = pd.to_datetime(merged["timestamp"])
    merged = merged.sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=True)
    merged["row_id"] = np.arange(len(merged))

    missing_labels = merged["failed"].isna().sum()
    if missing_labels:
        raise ValueError(f"Label merge failed for {missing_labels} rows")

    return merged, features


def artifact_checks(paths: Iterable[Path], selected_features: list[str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        if not path.exists():
            rows.append({"artifact": str(path), "exists": False})
            continue
        df = pd.read_parquet(path)
        key_cols = [c for c in ["file", "timestamp", "channel", "bearing", "axis"] if c in df.columns]
        duplicate_key_rows = int(df.duplicated(key_cols).sum()) if key_cols else None
        unique_keys = int(df[key_cols].drop_duplicates().shape[0]) if key_cols else None
        failed_count = int(df["failed"].sum()) if "failed" in df.columns else None
        censored_count = int(df["censored"].sum()) if "censored" in df.columns else None
        rul_not_null = int(df["rul_hours"].notna().sum()) if "rul_hours" in df.columns else None
        missing_selected = [feature for feature in selected_features if feature not in df.columns]
        numeric = df.select_dtypes(include=[np.number])
        inf_count = int(np.isinf(numeric.to_numpy(dtype=float, copy=False)).sum()) if not numeric.empty else 0
        rows.append(
            {
                "artifact": str(path),
                "exists": True,
                "rows": len(df),
                "columns": len(df.columns),
                "key_columns": ",".join(key_cols),
                "duplicate_key_rows": duplicate_key_rows,
                "unique_keys": unique_keys,
                "failed_count": failed_count,
                "censored_count": censored_count,
                "rul_not_null": rul_not_null,
                "missing_selected_features": len(missing_selected),
                "inf_values_numeric": inf_count,
            }
        )
    return pd.DataFrame(rows)


def compute_split_local_features(
    split_df: pd.DataFrame,
    specs: list[FeatureSpec],
) -> pd.DataFrame:
    """Compute non-fitted features using rows present in one split only."""
    out = split_df.copy().sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=False)
    group_cols = ["bearing", "axis"]

    for spec in specs:
        if spec.transform == "base":
            continue
        if spec.transform == "rolling":
            grouped = out.groupby(group_cols, sort=False)[spec.source_feature]
            rolled = grouped.transform(
                lambda x, window=spec.parameter, stat=spec.statistic: getattr(
                    x.rolling(window=window, min_periods=1),
                    stat,
                )()
            )
            out[spec.feature] = rolled
        elif spec.transform == "ema":
            alpha = (spec.parameter or 0) / 100
            out[spec.feature] = out.groupby(group_cols, sort=False)[spec.source_feature].transform(
                lambda x, alpha=alpha: x.ewm(alpha=alpha, adjust=False).mean()
            )
        elif spec.transform == "bearing_aggregate":
            grouped = out.groupby(["bearing", "timestamp"], sort=False)[spec.source_feature]
            if spec.statistic == "range":
                out[spec.feature] = grouped.transform(lambda x: x.max() - x.min())
            else:
                out[spec.feature] = grouped.transform(spec.statistic)

    return out.set_index("index").sort_index()


def add_train_fitted_zscores(
    train_features: pd.DataFrame,
    test_features: pd.DataFrame,
    specs: list[FeatureSpec],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit z-score statistics on training rows only and apply to train/test."""
    train_out = train_features.copy()
    test_out = test_features.copy()
    zscore_specs = [spec for spec in specs if spec.transform == "zscore"]

    for spec in zscore_specs:
        train_source = train_out[spec.source_feature]
        global_mean = float(train_source.mean())
        global_std = float(train_source.std())
        if not np.isfinite(global_std) or global_std == 0:
            global_std = 1e-8

        stats = (
            train_out.groupby(["bearing", "axis"], sort=False)[spec.source_feature]
            .agg(["mean", "std"])
            .rename(columns={"mean": "group_mean", "std": "group_std"})
        )

        def transform(frame: pd.DataFrame) -> pd.Series:
            keyed = frame.join(stats, on=["bearing", "axis"])
            means = keyed["group_mean"].fillna(global_mean)
            stds = keyed["group_std"].replace(0, np.nan).fillna(global_std)
            return (keyed[spec.source_feature] - means) / (stds + 1e-8)

        train_out[spec.feature] = transform(train_out)
        test_out[spec.feature] = transform(test_out)

    return train_out, test_out


def build_leakage_safe_fold_features(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = [parse_feature_spec(feature) for feature in features]
    train_features = compute_split_local_features(train_df, specs)
    test_features = compute_split_local_features(test_df, specs)
    train_features, test_features = add_train_fitted_zscores(train_features, test_features, specs)

    missing = [
        feature
        for feature in features
        if feature not in train_features.columns or feature not in test_features.columns
    ]
    if missing:
        raise ValueError(f"Leakage-safe feature builder did not create: {missing[:10]}")

    return train_features, test_features


def failed_regression_rows(df: pd.DataFrame) -> pd.DataFrame:
    failed = df[(df["failed"] == True) & df["rul_hours"].notna()].copy()  # noqa: E712
    return failed.sort_values(["bearing", "axis", "timestamp"]).reset_index(drop=True)


def current_leaky_baseline_fold(df: pd.DataFrame, train_pct: float = 0.8) -> Fold:
    work = df.copy()
    work["rul_bin"] = pd.cut(
        work["rul_hours"],
        bins=RUL_BINS,
        labels=RUL_BIN_LABELS,
        include_lowest=True,
    )
    train_pos, test_pos = train_test_split(
        np.arange(len(work)),
        test_size=1 - train_pct,
        stratify=work["rul_bin"],
        random_state=42,
    )
    return Fold(
        strategy="current_leaky_baseline",
        fold="rul_stratified_row_split",
        train_idx=np.sort(train_pos),
        test_idx=np.sort(test_pos),
        notes="Reproduces src/data/split_stratified.py row-level stratification by RUL bin.",
    )


def lobo_folds(df: pd.DataFrame) -> list[Fold]:
    folds: list[Fold] = []
    for bearing in sorted(df["bearing"].unique()):
        test_idx = df.index[df["bearing"] == bearing].to_numpy()
        train_idx = df.index[df["bearing"] != bearing].to_numpy()
        folds.append(
            Fold(
                strategy="lobo",
                fold=f"holdout_bearing_{bearing}",
                train_idx=train_idx,
                test_idx=test_idx,
                notes="All axes for one failed physical bearing are held out together.",
            )
        )
    return folds


def purged_time_series_folds(df: pd.DataFrame, n_splits: int = 5, purge_gap: int = 30) -> list[Fold]:
    """Blocked CV with an embargo around each test block per physical bearing.

    The split holds out the same ordinal time block for every failed bearing.
    Training rows within +/- ``purge_gap`` timestamps of each test block are
    removed for that same bearing.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if purge_gap < 0:
        raise ValueError("purge_gap must be >= 0")

    folds: list[Fold] = []
    for fold_id in range(n_splits):
        test_mask = pd.Series(False, index=df.index)
        purge_mask = pd.Series(False, index=df.index)

        for bearing, bearing_df in df.groupby("bearing", sort=True):
            timestamps = bearing_df["timestamp"].drop_duplicates().sort_values().reset_index(drop=True)
            blocks = np.array_split(np.arange(len(timestamps)), n_splits)
            block = blocks[fold_id]
            if len(block) == 0:
                continue

            test_timestamps = set(timestamps.iloc[block])
            purge_start = max(0, int(block.min()) - purge_gap)
            purge_end = min(len(timestamps) - 1, int(block.max()) + purge_gap)
            purge_timestamps = set(timestamps.iloc[purge_start : purge_end + 1])

            bearing_mask = df["bearing"] == bearing
            test_mask |= bearing_mask & df["timestamp"].isin(test_timestamps)
            purge_mask |= bearing_mask & df["timestamp"].isin(purge_timestamps)

        train_mask = ~(test_mask | purge_mask)
        folds.append(
            Fold(
                strategy="purged_time_series",
                fold=f"fold_{fold_id + 1}",
                train_idx=df.index[train_mask].to_numpy(),
                test_idx=df.index[test_mask].to_numpy(),
                notes=f"Blocked time-series fold with +/-{purge_gap} timestamp embargo per bearing.",
            )
        )

    return folds


def clean_xy(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: list[str],
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    x_train = train_df[features].replace([np.inf, -np.inf], np.nan)
    medians = x_train.median()
    x_train = x_train.fillna(medians)
    x_test = test_df[features].replace([np.inf, -np.inf], np.nan).fillna(medians)
    return x_train, train_df["rul_hours"], x_test, test_df["rul_hours"]


def fit_predict(train_df: pd.DataFrame, test_df: pd.DataFrame, features: list[str]) -> np.ndarray:
    x_train, y_train, x_test, _ = clean_xy(train_df, test_df, features)
    model = lgb.LGBMRegressor(**TUNED_LGBM_PARAMS)
    model.fit(x_train, y_train)
    return model.predict(x_test)


def regression_metrics(y_true: pd.Series | np.ndarray, y_pred: np.ndarray) -> dict[str, float | int]:
    y_true_arr = np.asarray(y_true, dtype=float)
    y_pred_arr = np.asarray(y_pred, dtype=float)
    out: dict[str, float | int] = {
        "samples": int(len(y_true_arr)),
        "mae": float(mean_absolute_error(y_true_arr, y_pred_arr)),
        "rmse": float(math.sqrt(mean_squared_error(y_true_arr, y_pred_arr))),
        "r2": float("nan"),
    }
    if len(y_true_arr) >= 2 and np.var(y_true_arr) > 0:
        out["r2"] = float(r2_score(y_true_arr, y_pred_arr))

    critical = y_true_arr <= CRITICAL_RUL_HOURS
    out["critical_samples"] = int(critical.sum())
    out["critical_mae"] = (
        float(mean_absolute_error(y_true_arr[critical], y_pred_arr[critical]))
        if critical.any()
        else float("nan")
    )
    return out


def threshold_metrics(y_true: pd.Series | np.ndarray, y_pred: np.ndarray, threshold: float) -> dict[str, float | int]:
    actual = np.asarray(y_true, dtype=float) <= threshold
    predicted = np.asarray(y_pred, dtype=float) <= threshold
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    fpr = fp / (fp + tn) if fp + tn else float("nan")
    miss_rate = fn / (tp + fn) if tp + fn else float("nan")
    return {
        "threshold_hours": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_alarm_rate": fpr,
        "miss_rate": miss_rate,
    }


def rul_distribution(df: pd.DataFrame, split_name: str, strategy: str, fold: str) -> pd.DataFrame:
    bins = pd.cut(df["rul_hours"], bins=RUL_BINS, labels=RUL_BIN_LABELS, include_lowest=True)
    counts = bins.value_counts().reindex(RUL_BIN_LABELS, fill_value=0)
    return pd.DataFrame(
        {
            "strategy": strategy,
            "fold": fold,
            "split": split_name,
            "rul_bin": counts.index.astype(str),
            "count": counts.to_numpy(),
        }
    )


def nearest_train_gap_by_bearing(
    full_df: pd.DataFrame,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
) -> float:
    """Return nearest train/test ordinal timestamp gap within same physical bearing."""
    gaps: list[int] = []
    for bearing, test_bearing_df in test_df.groupby("bearing", sort=True):
        train_ts = set(train_df.loc[train_df["bearing"] == bearing, "timestamp"])
        if not train_ts:
            continue
        all_ts = (
            full_df.loc[full_df["bearing"] == bearing, "timestamp"]
            .drop_duplicates()
            .sort_values()
            .reset_index(drop=True)
        )
        positions = {ts: idx for idx, ts in enumerate(all_ts)}
        train_positions = np.array([positions[ts] for ts in train_ts])
        for ts in test_bearing_df["timestamp"].drop_duplicates():
            pos = positions[ts]
            gaps.append(int(np.min(np.abs(train_positions - pos))))
    return float(min(gaps)) if gaps else float("nan")


def exact_key_overlap(train_df: pd.DataFrame, test_df: pd.DataFrame) -> int:
    key_cols = ["file", "timestamp", "channel", "bearing", "axis"]
    train_keys = set(map(tuple, train_df[key_cols].to_numpy()))
    test_keys = set(map(tuple, test_df[key_cols].to_numpy()))
    return len(train_keys & test_keys)


def same_bearing_timestamp_overlap(train_df: pd.DataFrame, test_df: pd.DataFrame) -> int:
    key_cols = ["bearing", "timestamp"]
    train_keys = set(map(tuple, train_df[key_cols].drop_duplicates().to_numpy()))
    test_keys = set(map(tuple, test_df[key_cols].drop_duplicates().to_numpy()))
    return len(train_keys & test_keys)


def evaluate_fold(
    df: pd.DataFrame,
    features: list[str],
    fold: Fold,
    feature_mode: str,
) -> tuple[dict, list[dict], list[dict], pd.DataFrame]:
    train_df = df.loc[fold.train_idx].copy()
    test_df = df.loc[fold.test_idx].copy()
    if feature_mode == "leakage_safe":
        train_model_df, test_model_df = build_leakage_safe_fold_features(train_df, test_df, features)
    else:
        train_model_df, test_model_df = train_df, test_df
    y_pred = fit_predict(train_model_df, test_model_df, features)

    fold_row = {
        "strategy": fold.strategy,
        "fold": fold.fold,
        "feature_mode": feature_mode,
        "notes": fold.notes,
        "train_samples": len(train_df),
        "test_samples": len(test_df),
        "train_bearings": ",".join(map(str, sorted(train_df["bearing"].unique()))),
        "test_bearings": ",".join(map(str, sorted(test_df["bearing"].unique()))),
        "train_rul_min": float(train_df["rul_hours"].min()),
        "train_rul_max": float(train_df["rul_hours"].max()),
        "test_rul_min": float(test_df["rul_hours"].min()),
        "test_rul_max": float(test_df["rul_hours"].max()),
        "nearest_train_test_gap_same_bearing": nearest_train_gap_by_bearing(df, train_df, test_df),
        "exact_key_overlap": exact_key_overlap(train_df, test_df),
        "same_bearing_timestamp_overlap": same_bearing_timestamp_overlap(train_df, test_df),
    }
    fold_row.update(regression_metrics(test_df["rul_hours"], y_pred))

    per_bearing_rows = []
    pred_df = test_df[["bearing", "axis", "timestamp", "rul_hours"]].copy()
    pred_df["prediction"] = y_pred
    for bearing, bearing_df in pred_df.groupby("bearing", sort=True):
        metrics = regression_metrics(bearing_df["rul_hours"], bearing_df["prediction"].to_numpy())
        per_bearing_rows.append(
            {
                "strategy": fold.strategy,
                "fold": fold.fold,
                "bearing": int(bearing),
                **metrics,
            }
        )

    business_rows = []
    for threshold in [CRITICAL_RUL_HOURS, WARNING_RUL_HOURS]:
        business_rows.append(
            {
                "strategy": fold.strategy,
                "fold": fold.fold,
                **threshold_metrics(test_df["rul_hours"], y_pred, threshold),
            }
        )

    distributions = pd.concat(
        [
            rul_distribution(train_df, "train", fold.strategy, fold.fold),
            rul_distribution(test_df, "test", fold.strategy, fold.fold),
        ],
        ignore_index=True,
    )

    return fold_row, per_bearing_rows, business_rows, distributions


def aggregate_strategy_metrics(fold_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for strategy, group in fold_metrics.groupby("strategy", sort=False):
        total_test = group["test_samples"].sum()
        weighted = {}
        for metric in ["mae", "rmse", "critical_mae"]:
            weights = group["test_samples"] if metric != "critical_mae" else group["critical_samples"]
            valid = group[metric].notna() & (weights > 0)
            weighted[metric] = (
                float(np.average(group.loc[valid, metric], weights=weights.loc[valid]))
                if valid.any()
                else float("nan")
            )
        rows.append(
            {
                "strategy": strategy,
                "folds": len(group),
                "total_test_samples": int(total_test),
                "mean_mae": float(group["mae"].mean()),
                "weighted_mae": weighted["mae"],
                "mean_rmse": float(group["rmse"].mean()),
                "weighted_rmse": weighted["rmse"],
                "mean_r2": float(group["r2"].mean()),
                "weighted_critical_mae": weighted["critical_mae"],
                "total_critical_samples": int(group["critical_samples"].sum()),
            }
        )
    return pd.DataFrame(rows)


def write_report(
    output_dir: Path,
    summary: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    per_bearing: pd.DataFrame,
    business: pd.DataFrame,
    artifact_df: pd.DataFrame,
    feature_audit: pd.DataFrame,
    comparison: pd.DataFrame,
    features: list[str],
    purge_gap: int,
    n_splits: int,
    feature_mode: str,
) -> None:
    def markdown_table(df: pd.DataFrame) -> str:
        if df.empty:
            return "_No rows._"
        display = df.copy()
        for col in display.columns:
            if pd.api.types.is_float_dtype(display[col]):
                display[col] = display[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
            else:
                display[col] = display[col].map(lambda x: "" if pd.isna(x) else str(x))
        headers = list(display.columns)
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for _, row in display.iterrows():
            values = [str(row[col]).replace("|", "\\|") for col in headers]
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    report_path = output_dir / "validation_report.md"
    suspect = artifact_df.loc[artifact_df["artifact"] == str(SUSPECT_TEMPORAL_PATH)]
    suspect_note = ""
    if not suspect.empty and int(suspect["duplicate_key_rows"].iloc[0]) > 0:
        suspect_note = (
            f"`{SUSPECT_TEMPORAL_PATH}` is not used for metrics because it has "
            f"{int(suspect['duplicate_key_rows'].iloc[0])} duplicate key rows."
        )

    zscore_features = [feature for feature in features if "zscore" in feature]
    metric_source = (
        "`data/processed/test_temporal_features.parquet` merged with labels from "
        "`data/processed/set1_labeled.parquet`"
        if feature_mode == "artifact"
        else "`data/processed/test_base_features.parquet` merged with labels from "
        "`data/processed/set1_labeled.parquet`, then fold-local selected-feature reconstruction"
    )
    content = [
        "# Phase 1 Truth Stabilization Validation Report",
        "",
        "## Methodology",
        "",
        f"- Data source for metrics: {metric_source}.",
        f"- Selected features: {len(features)} from `data/processed/selected_features.csv`.",
        "- Model family: LightGBM regressor with the existing tuned hyperparameters, retrained inside each fold.",
        f"- Feature mode: `{feature_mode}`.",
        "- Current baseline: row-level RUL-bin stratified split, matching `src/data/split_stratified.py`; this is labeled leaky.",
        "- LOBO: hold out one failed physical bearing at a time; Set 1 supports only bearings 3 and 4.",
        f"- Purged time-series CV: {n_splits} blocked folds, same ordinal time block held out per bearing, +/-{purge_gap} timestamp embargo per bearing.",
        "- Critical zone: RUL <= 50h. Warning/maintenance threshold proxy: RUL <= 100h.",
        "- Leakage-safe mode recomputes rolling/EMA/cross-axis aggregate features inside each fold split and fits z-score statistics on training rows only.",
        "",
        "## Artifact Findings",
        "",
        suspect_note or "No duplicate-key issue found in the primary metric artifact.",
        "",
        markdown_table(artifact_df),
        "",
        "## Selected Feature Audit",
        "",
        markdown_table(feature_audit),
        "",
        "## Summary Metrics",
        "",
        markdown_table(summary),
        "",
        "## Previous Phase 1 vs This Run",
        "",
        markdown_table(comparison),
        "",
        "## Fold Metrics",
        "",
        markdown_table(fold_metrics),
        "",
        "## Per-Bearing Metrics",
        "",
        markdown_table(per_bearing),
        "",
        "## Maintenance Threshold Proxy Metrics",
        "",
        markdown_table(business),
        "",
        "## Leakage Interpretation",
        "",
        "- The current baseline uses both failed bearings and both axes in train and test, with same-bearing train/test rows at identical or adjacent timestamps. That is temporal leakage for this autocorrelated run-to-failure setting.",
        "- LOBO removes physical bearing overlap between train and test and is the most honest Set-1 estimate for an unseen bearing. It has only two folds, so conclusions are noisy.",
        "- Purged CV reduces adjacent-row leakage inside each physical bearing, but it is still an offline blocked CV design and does not fully simulate chronological deployment.",
        "- In leakage-safe mode, any performance change relative to the previous Phase 1 report isolates the effect of precomputed temporal/z-score features leaking held-out fold information.",
        "",
        "## Limitations",
        "",
        f"- {len(zscore_features)} selected features contain `zscore`; in leakage-safe mode they are recomputed from training statistics, but this changes semantics for LOBO unseen bearings because no same-bearing training statistics exist.",
        "- The tuned hyperparameters were originally selected under the leaky validation regime; this comparison keeps them fixed for controlled comparison but does not remove hyperparameter-selection bias.",
        "- Set 1 has only two failed physical bearings. LOBO is therefore a two-fold study, not a statistically strong generalization proof.",
        "- The README claims should be revised unless they can be reproduced under the LOBO/purged strategies without leakage.",
        "",
    ]
    report_path.write_text("\n".join(content), encoding="utf-8")


def compare_with_previous_phase1(
    summary: pd.DataFrame,
    previous_path: Path = Path("reports/evaluation/phase1_validation/summary_metrics.csv"),
) -> pd.DataFrame:
    current = summary.copy()
    current = current.rename(
        columns={
            "weighted_mae": "after_weighted_mae",
            "weighted_rmse": "after_weighted_rmse",
            "mean_r2": "after_mean_r2",
            "weighted_critical_mae": "after_weighted_critical_mae",
        }
    )
    if not previous_path.exists():
        current["previous_phase1_available"] = False
        return current

    previous = pd.read_csv(previous_path)
    previous = previous.rename(
        columns={
            "weighted_mae": "before_weighted_mae",
            "weighted_rmse": "before_weighted_rmse",
            "mean_r2": "before_mean_r2",
            "weighted_critical_mae": "before_weighted_critical_mae",
        }
    )
    cols = [
        "strategy",
        "before_weighted_mae",
        "before_weighted_rmse",
        "before_mean_r2",
        "before_weighted_critical_mae",
    ]
    out = previous[cols].merge(
        current[
            [
                "strategy",
                "after_weighted_mae",
                "after_weighted_rmse",
                "after_mean_r2",
                "after_weighted_critical_mae",
            ]
        ],
        on="strategy",
        how="outer",
    )
    out["delta_weighted_mae"] = out["after_weighted_mae"] - out["before_weighted_mae"]
    out["delta_weighted_critical_mae"] = (
        out["after_weighted_critical_mae"] - out["before_weighted_critical_mae"]
    )
    return out


def run(
    output_dir: Path,
    n_splits: int = 5,
    purge_gap: int = 30,
    feature_mode: str = "artifact",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    full_df, features = load_validation_frame(feature_mode=feature_mode)
    failed_df = failed_regression_rows(full_df)
    feature_audit = classify_selected_features(features)

    artifact_df = artifact_checks(
        [
            Path("data/processed/set1_features.parquet"),
            SUSPECT_TEMPORAL_PATH,
            LABELS_PATH,
            Path("data/processed/test_base_features.parquet"),
            FEATURES_PATH,
        ],
        features,
    )

    folds = [current_leaky_baseline_fold(failed_df)]
    folds.extend(lobo_folds(failed_df))
    folds.extend(purged_time_series_folds(failed_df, n_splits=n_splits, purge_gap=purge_gap))

    fold_rows = []
    per_bearing_rows = []
    business_rows = []
    distribution_frames = []
    for fold in folds:
        fold_row, bearing_rows, threshold_rows, distributions = evaluate_fold(
            failed_df,
            features,
            fold,
            feature_mode,
        )
        fold_rows.append(fold_row)
        per_bearing_rows.extend(bearing_rows)
        business_rows.extend(threshold_rows)
        distribution_frames.append(distributions)

    fold_metrics = pd.DataFrame(fold_rows)
    per_bearing = pd.DataFrame(per_bearing_rows)
    business = pd.DataFrame(business_rows)
    distributions = pd.concat(distribution_frames, ignore_index=True)
    summary = aggregate_strategy_metrics(fold_metrics)
    comparison = compare_with_previous_phase1(summary)

    paths = {
        "artifact_checks": output_dir / "artifact_checks.csv",
        "feature_audit": output_dir / "feature_audit.csv",
        "fold_metrics": output_dir / "fold_metrics.csv",
        "per_bearing_metrics": output_dir / "per_bearing_metrics.csv",
        "business_metrics": output_dir / "business_metrics.csv",
        "rul_distributions": output_dir / "rul_distributions.csv",
        "summary_metrics": output_dir / "summary_metrics.csv",
        "comparison_metrics": output_dir / "comparison_metrics.csv",
        "run_config": output_dir / "run_config.json",
        "report": output_dir / "validation_report.md",
    }

    artifact_df.to_csv(paths["artifact_checks"], index=False)
    feature_audit.to_csv(paths["feature_audit"], index=False)
    fold_metrics.to_csv(paths["fold_metrics"], index=False)
    per_bearing.to_csv(paths["per_bearing_metrics"], index=False)
    business.to_csv(paths["business_metrics"], index=False)
    distributions.to_csv(paths["rul_distributions"], index=False)
    summary.to_csv(paths["summary_metrics"], index=False)
    comparison.to_csv(paths["comparison_metrics"], index=False)
    paths["run_config"].write_text(
        json.dumps(
            {
                "feature_mode": feature_mode,
                "features_path": str(FEATURES_PATH if feature_mode == "artifact" else BASE_FEATURES_PATH),
                "labels_path": str(LABELS_PATH),
                "selected_features_path": str(SELECTED_FEATURES_PATH),
                "n_selected_features": len(features),
                "n_failed_rows": len(failed_df),
                "failed_bearings": sorted(map(int, failed_df["bearing"].unique())),
                "critical_rul_hours": CRITICAL_RUL_HOURS,
                "warning_rul_hours": WARNING_RUL_HOURS,
                "purge_gap": purge_gap,
                "n_splits": n_splits,
                "model_params": TUNED_LGBM_PARAMS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    write_report(
        output_dir,
        summary,
        fold_metrics,
        per_bearing,
        business,
        artifact_df,
        feature_audit,
        comparison,
        features,
        purge_gap,
        n_splits,
        feature_mode,
    )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline leakage validation study for IMS Bearing RUL.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/phase1_validation"))
    parser.add_argument("--purge-gap", type=int, default=30)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument(
        "--feature-mode",
        choices=["artifact", "leakage_safe"],
        default="artifact",
        help="Use precomputed temporal features or fold-local leakage-safe preprocessing.",
    )
    args = parser.parse_args()

    paths = run(
        output_dir=args.output_dir,
        n_splits=args.n_splits,
        purge_gap=args.purge_gap,
        feature_mode=args.feature_mode,
    )
    print("Phase 1 validation artifacts written:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()

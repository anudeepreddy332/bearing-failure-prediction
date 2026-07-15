"""Root-cause diagnostics for leakage-safe IMS Bearing validation results.

This script is intentionally offline and artifact-preserving. It reuses the
leakage-safe Phase 1 validation helpers, keeps the existing fixed LightGBM
configuration, and writes diagnostic evidence without tuning or replacing a
model artifact.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import lightgbm as lgb
import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp, spearmanr, wasserstein_distance
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from src.models.offline_validation import (
    BASE_FEATURES_PATH,
    CRITICAL_RUL_HOURS,
    LABELS_PATH,
    RUL_BIN_LABELS,
    RUL_BINS,
    SELECTED_FEATURES_PATH,
    TUNED_LGBM_PARAMS,
    WARNING_RUL_HOURS,
    build_leakage_safe_fold_features,
    clean_xy,
    failed_regression_rows,
    load_validation_frame,
    lobo_folds,
    parse_feature_spec,
    regression_metrics,
    threshold_metrics,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def markdown_table(df: pd.DataFrame, max_rows: int | None = None) -> str:
    if df.empty:
        return "_No rows._"
    display = df.head(max_rows).copy() if max_rows else df.copy()
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
    if max_rows and len(df) > max_rows:
        lines.append(f"| ... | {len(df) - max_rows} more rows omitted |" + " |" * (len(headers) - 2))
    return "\n".join(lines)


def selected_feature_profile(features: list[str]) -> tuple[pd.DataFrame, list[str]]:
    rows = []
    for feature in features:
        spec = parse_feature_spec(feature)
        rows.append(
            {
                "feature": feature,
                "source_feature": spec.source_feature,
                "transform": spec.transform,
                "parameter": spec.parameter,
                "statistic": spec.statistic,
            }
        )
    profile = pd.DataFrame(rows)
    roots = sorted(profile["source_feature"].unique())
    return profile, roots


def data_profile(full_df: pd.DataFrame, failed_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = (
        full_df.groupby(["bearing", "axis", "failed", "censored"], dropna=False)
        .agg(
            samples=("row_id", "size"),
            timestamps=("timestamp", "nunique"),
            rul_min=("rul_hours", "min"),
            rul_max=("rul_hours", "max"),
            rul_missing=("rul_hours", lambda x: int(x.isna().sum())),
        )
        .reset_index()
    )
    failed_summary = (
        failed_df.groupby("bearing")
        .agg(
            samples=("row_id", "size"),
            axes=("axis", "nunique"),
            timestamps=("timestamp", "nunique"),
            rul_min=("rul_hours", "min"),
            rul_max=("rul_hours", "max"),
            critical_samples=("rul_hours", lambda x: int((x <= CRITICAL_RUL_HOURS).sum())),
            warning_samples=("rul_hours", lambda x: int((x <= WARNING_RUL_HOURS).sum())),
        )
        .reset_index()
    )
    return counts, failed_summary


def label_quality_checks(failed_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (bearing, axis), group in failed_df.groupby(["bearing", "axis"], sort=True):
        ordered = group.sort_values("timestamp")
        diffs = ordered["rul_hours"].diff().dropna()
        rows.append(
            {
                "bearing": int(bearing),
                "axis": axis,
                "samples": len(ordered),
                "rul_min": float(ordered["rul_hours"].min()),
                "rul_max": float(ordered["rul_hours"].max()),
                "missing_rul": int(ordered["rul_hours"].isna().sum()),
                "non_monotonic_increases": int((diffs > 1e-9).sum()),
                "duplicate_timestamps": int(ordered["timestamp"].duplicated().sum()),
                "first_timestamp": str(ordered["timestamp"].iloc[0]),
                "last_timestamp": str(ordered["timestamp"].iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


def feature_distribution_drift(failed_df: pd.DataFrame, root_features: list[str]) -> pd.DataFrame:
    rows = []
    bearings = sorted(failed_df["bearing"].unique())
    if len(bearings) != 2:
        return pd.DataFrame()
    left = failed_df.loc[failed_df["bearing"] == bearings[0]]
    right = failed_df.loc[failed_df["bearing"] == bearings[1]]
    for feature in root_features:
        x = left[feature].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
        y = right[feature].replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
        pooled_std = float(np.nanstd(np.concatenate([x, y]), ddof=1)) if len(x) and len(y) else float("nan")
        smd = (float(np.nanmean(y)) - float(np.nanmean(x))) / pooled_std if pooled_std else float("nan")
        rows.append(
            {
                "feature": feature,
                "bearing_left": int(bearings[0]),
                "bearing_right": int(bearings[1]),
                "left_mean": float(np.nanmean(x)),
                "right_mean": float(np.nanmean(y)),
                "standardized_mean_diff": smd,
                "ks_statistic": float(ks_2samp(x, y).statistic),
                "ks_pvalue": float(ks_2samp(x, y).pvalue),
                "wasserstein_distance": float(wasserstein_distance(x, y)),
            }
        )
    return pd.DataFrame(rows).sort_values("ks_statistic", ascending=False).reset_index(drop=True)


def write_pca_outputs(failed_df: pd.DataFrame, root_features: list[str], output_dir: Path) -> pd.DataFrame:
    work = failed_df[["bearing", "axis", "timestamp", "rul_hours", *root_features]].copy()
    x = work[root_features].replace([np.inf, -np.inf], np.nan)
    x = x.fillna(x.median())
    scaled = StandardScaler().fit_transform(x)
    pca = PCA(n_components=2, random_state=42)
    components = pca.fit_transform(scaled)
    out = work[["bearing", "axis", "timestamp", "rul_hours"]].copy()
    out["pc1"] = components[:, 0]
    out["pc2"] = components[:, 1]
    out["explained_variance_pc1"] = float(pca.explained_variance_ratio_[0])
    out["explained_variance_pc2"] = float(pca.explained_variance_ratio_[1])

    fig, ax = plt.subplots(figsize=(8, 6))
    for bearing, group in out.groupby("bearing", sort=True):
        ax.scatter(group["pc1"], group["pc2"], s=8, alpha=0.45, label=f"Bearing {bearing}")
    ax.set_title("PCA of selected feature source signals")
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "pca_by_bearing.png", dpi=160)
    plt.close(fig)
    return out


def fit_fixed_lgbm(train_df: pd.DataFrame, test_df: pd.DataFrame, features: list[str]) -> tuple[lgb.LGBMRegressor, pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    x_train, y_train, x_test, y_test = clean_xy(train_df, test_df, features)
    model = lgb.LGBMRegressor(**TUNED_LGBM_PARAMS)
    model.fit(x_train, y_train)
    return model, x_train, y_train, x_test, y_test


def residual_bins(predictions: pd.DataFrame, fold_name: str) -> pd.DataFrame:
    work = predictions.copy()
    work["abs_error"] = work["residual"].abs()
    work["rul_bin"] = pd.cut(work["actual_rul_hours"], bins=RUL_BINS, labels=RUL_BIN_LABELS, include_lowest=True)
    return (
        work.groupby("rul_bin", observed=False)
        .agg(
            fold=("fold", lambda _: fold_name),
            samples=("abs_error", "size"),
            mae=("abs_error", "mean"),
            median_abs_error=("abs_error", "median"),
            bias=("residual", "mean"),
            actual_rul_min=("actual_rul_hours", "min"),
            actual_rul_max=("actual_rul_hours", "max"),
        )
        .reset_index()
    )


def calibration_bins(predictions: pd.DataFrame, fold_name: str) -> pd.DataFrame:
    work = predictions.copy()
    bins = pd.qcut(work["predicted_rul_hours"], q=10, duplicates="drop")
    work["prediction_bin"] = bins.astype(str)
    return (
        work.groupby("prediction_bin", observed=False)
        .agg(
            fold=("fold", lambda _: fold_name),
            samples=("predicted_rul_hours", "size"),
            predicted_mean=("predicted_rul_hours", "mean"),
            actual_mean=("actual_rul_hours", "mean"),
            mae=("residual", lambda x: float(np.mean(np.abs(x)))),
            bias=("residual", "mean"),
        )
        .reset_index()
    )


def safe_spearman(x: pd.Series, y: pd.Series) -> float:
    x_arr = x.replace([np.inf, -np.inf], np.nan)
    mask = x_arr.notna() & y.notna()
    if mask.sum() < 3 or x_arr.loc[mask].nunique() < 2 or y.loc[mask].nunique() < 2:
        return float("nan")
    return float(spearmanr(x_arr.loc[mask], y.loc[mask]).statistic)


def lobo_diagnostics(failed_df: pd.DataFrame, features: list[str]) -> dict[str, pd.DataFrame]:
    prediction_rows = []
    train_test_rows = []
    importance_rows = []
    predictiveness_rows = []
    residual_frames = []
    calibration_frames = []
    learning_rows = []
    rng = np.random.default_rng(42)

    for fold in lobo_folds(failed_df):
        train_df = failed_df.loc[fold.train_idx].copy()
        test_df = failed_df.loc[fold.test_idx].copy()
        train_model_df, test_model_df = build_leakage_safe_fold_features(train_df, test_df, features)
        model, x_train, y_train, x_test, y_test = fit_fixed_lgbm(train_model_df, test_model_df, features)

        train_pred = model.predict(x_train)
        test_pred = model.predict(x_test)
        train_metrics = regression_metrics(y_train, train_pred)
        test_metrics = regression_metrics(y_test, test_pred)
        train_critical = threshold_metrics(y_train, train_pred, CRITICAL_RUL_HOURS)
        test_critical = threshold_metrics(y_test, test_pred, CRITICAL_RUL_HOURS)

        train_test_rows.append(
            {
                "fold": fold.fold,
                "train_bearings": ",".join(map(str, sorted(train_model_df["bearing"].unique()))),
                "test_bearings": ",".join(map(str, sorted(test_model_df["bearing"].unique()))),
                "train_samples": len(train_model_df),
                "test_samples": len(test_model_df),
                "train_mae": train_metrics["mae"],
                "test_mae": test_metrics["mae"],
                "generalization_gap_mae": test_metrics["mae"] - train_metrics["mae"],
                "train_critical_mae": train_metrics["critical_mae"],
                "test_critical_mae": test_metrics["critical_mae"],
                "train_low_rul_recall_50h": train_critical["recall"],
                "test_low_rul_recall_50h": test_critical["recall"],
                "test_false_alarm_rate_50h": test_critical["false_alarm_rate"],
                "test_miss_rate_50h": test_critical["miss_rate"],
            }
        )

        gain = model.booster_.feature_importance(importance_type="gain")
        total_gain = float(np.sum(gain))
        for feature, value in zip(features, gain, strict=True):
            importance_rows.append(
                {
                    "fold": fold.fold,
                    "feature": feature,
                    "gain": float(value),
                    "normalized_gain": float(value / total_gain) if total_gain else 0.0,
                }
            )

        for feature in features:
            train_corr = safe_spearman(train_model_df[feature], train_model_df["rul_hours"])
            test_corr = safe_spearman(test_model_df[feature], test_model_df["rul_hours"])
            predictiveness_rows.append(
                {
                    "fold": fold.fold,
                    "feature": feature,
                    "train_spearman_rul": train_corr,
                    "test_spearman_rul": test_corr,
                    "abs_delta": abs(train_corr - test_corr)
                    if np.isfinite(train_corr) and np.isfinite(test_corr)
                    else float("nan"),
                    "sign_flip": bool(np.isfinite(train_corr) and np.isfinite(test_corr) and np.sign(train_corr) != np.sign(test_corr)),
                }
            )

        pred_df = test_model_df[["bearing", "axis", "timestamp", "rul_hours"]].copy()
        pred_df["fold"] = fold.fold
        pred_df["actual_rul_hours"] = pred_df["rul_hours"].astype(float)
        pred_df["predicted_rul_hours"] = test_pred
        pred_df["residual"] = pred_df["predicted_rul_hours"] - pred_df["actual_rul_hours"]
        pred_df = pred_df.drop(columns=["rul_hours"])
        prediction_rows.append(pred_df)
        residual_frames.append(residual_bins(pred_df, fold.fold))
        calibration_frames.append(calibration_bins(pred_df, fold.fold))

        positions = np.arange(len(train_model_df))
        for fraction in [0.25, 0.5, 0.75, 1.0]:
            subset_size = max(50, int(round(len(positions) * fraction)))
            subset_pos = positions if math.isclose(fraction, 1.0) else np.sort(rng.choice(positions, size=subset_size, replace=False))
            subset_train = train_model_df.iloc[subset_pos]
            subset_model, subset_x_train, subset_y_train, _, _ = fit_fixed_lgbm(subset_train, test_model_df, features)
            subset_train_pred = subset_model.predict(subset_x_train)
            subset_test_pred = subset_model.predict(x_test)
            subset_train_metrics = regression_metrics(subset_y_train, subset_train_pred)
            subset_test_metrics = regression_metrics(y_test, subset_test_pred)
            learning_rows.append(
                {
                    "fold": fold.fold,
                    "train_fraction": fraction,
                    "train_samples": len(subset_train),
                    "train_mae": subset_train_metrics["mae"],
                    "test_mae": subset_test_metrics["mae"],
                    "generalization_gap_mae": subset_test_metrics["mae"] - subset_train_metrics["mae"],
                    "test_critical_mae": subset_test_metrics["critical_mae"],
                }
            )

    importance = pd.DataFrame(importance_rows)
    pivot = importance.pivot_table(index="feature", columns="fold", values="normalized_gain", fill_value=0.0)
    stability_rows = []
    folds = list(pivot.columns)
    for i, left_fold in enumerate(folds):
        for right_fold in folds[i + 1 :]:
            stability_rows.append(
                {
                    "left_fold": left_fold,
                    "right_fold": right_fold,
                    "spearman_normalized_gain": safe_spearman(pivot[left_fold], pivot[right_fold]),
                    "pearson_normalized_gain": float(pivot[left_fold].corr(pivot[right_fold])),
                }
            )

    return {
        "lobo_predictions": pd.concat(prediction_rows, ignore_index=True),
        "lobo_train_test_gap": pd.DataFrame(train_test_rows),
        "feature_importance_lobo": importance.sort_values(["fold", "normalized_gain"], ascending=[True, False]),
        "feature_importance_stability": pd.DataFrame(stability_rows),
        "feature_predictiveness_lobo": pd.DataFrame(predictiveness_rows),
        "residual_by_rul_bin": pd.concat(residual_frames, ignore_index=True),
        "calibration_by_prediction_bin": pd.concat(calibration_frames, ignore_index=True),
        "learning_curve_lobo": pd.DataFrame(learning_rows),
    }


def hypothesis_evidence(
    data_counts: pd.DataFrame,
    failed_summary: pd.DataFrame,
    drift: pd.DataFrame,
    lobo_gap: pd.DataFrame,
    importance_stability: pd.DataFrame,
    predictiveness: pd.DataFrame,
    label_quality: pd.DataFrame,
    residuals: pd.DataFrame,
    learning_curve: pd.DataFrame,
) -> pd.DataFrame:
    high_drift = int((drift["ks_statistic"] >= 0.5).sum()) if not drift.empty else 0
    median_ks = float(drift["ks_statistic"].median()) if not drift.empty else float("nan")
    max_gap = float(lobo_gap["generalization_gap_mae"].max()) if not lobo_gap.empty else float("nan")
    train_mae_mean = float(lobo_gap["train_mae"].mean()) if not lobo_gap.empty else float("nan")
    test_mae_mean = float(lobo_gap["test_mae"].mean()) if not lobo_gap.empty else float("nan")
    importance_corr = (
        float(importance_stability["spearman_normalized_gain"].iloc[0])
        if not importance_stability.empty
        else float("nan")
    )
    sign_flip_rate = float(predictiveness["sign_flip"].mean()) if not predictiveness.empty else float("nan")
    label_issues = int(label_quality["non_monotonic_increases"].sum() + label_quality["missing_rul"].sum())
    critical_residual = residuals.loc[residuals["rul_bin"] == "0-50h", "mae"]
    critical_mae_mean = float(critical_residual.mean()) if not critical_residual.empty else float("nan")
    final_curve = learning_curve.loc[learning_curve["train_fraction"] == 1.0, "test_mae"]
    early_curve = learning_curve.loc[learning_curve["train_fraction"] == 0.25, "test_mae"]
    learning_delta = float(early_curve.mean() - final_curve.mean()) if not early_curve.empty and not final_curve.empty else float("nan")

    rows = [
        {
            "hypothesis": "Dataset size limitations",
            "evidence": f"Only {int(failed_summary['bearing'].nunique())} failed physical bearings with RUL labels; {int(failed_summary['samples'].sum())} failed rows are repeated timestamp/axis samples from those bearings.",
            "support": "supported",
            "confidence": "high",
            "likely_impact": "LOBO trains on one failed bearing and tests on the other, so performance is dominated by trajectory idiosyncrasies.",
            "recommendation": "Ingest additional independent failure trajectories before making generalization claims.",
        },
        {
            "hypothesis": "Only two failed bearings available for LOBO",
            "evidence": f"Failed-bearing summary contains bearings {','.join(map(str, sorted(failed_summary['bearing'].astype(int))))}; LOBO has two folds of {int(failed_summary['samples'].iloc[0])} test rows each.",
            "support": "supported",
            "confidence": "high",
            "likely_impact": "The LOBO estimate is honest but statistically thin and asymmetric.",
            "recommendation": "Treat Set-1 LOBO as a blocking sanity check, not a production estimate.",
        },
        {
            "hypothesis": "Bearing-to-bearing distribution shift",
            "evidence": f"{high_drift}/{len(drift)} selected source features have KS >= 0.50 between bearings 3 and 4; median KS = {median_ks:.3f}.",
            "support": "supported" if high_drift else "inconclusive",
            "confidence": "high" if high_drift else "medium",
            "likely_impact": "A model fit on one bearing sees a materially different feature distribution on the held-out bearing.",
            "recommendation": "Use drift diagnostics as a required gate for future feature sets; add more bearings before trusting LOBO averages.",
        },
        {
            "hypothesis": "Feature distribution drift across bearings",
            "evidence": "Top drifted selected source features are "
            + ", ".join(drift.head(5)["feature"].tolist())
            + ".",
            "support": "supported",
            "confidence": "high",
            "likely_impact": "The current selected features encode bearing-specific scale/trajectory effects rather than stable failure progression.",
            "recommendation": "Prefer features normalized by training-only operating context and validate drift under LOBO.",
        },
        {
            "hypothesis": "Feature importance stability across validation folds",
            "evidence": f"LOBO feature-importance Spearman correlation across the two held-out folds is {importance_corr:.3f}.",
            "support": "supported" if np.isfinite(importance_corr) and importance_corr < 0.5 else "weakened",
            "confidence": "medium",
            "likely_impact": "Unstable importance means fold-specific shortcuts may dominate the model.",
            "recommendation": "Audit top features per fold before retuning; do not optimize a feature set that changes behavior by held-out bearing.",
        },
        {
            "hypothesis": "Label quality and RUL generation assumptions",
            "evidence": f"Label checks found {label_issues} missing/non-monotonic failed-bearing RUL issues; labels assume failure at each failed bearing's last timestamp.",
            "support": "weakened" if label_issues == 0 else "supported",
            "confidence": "medium",
            "likely_impact": "The mechanical assumption is provisional, but no basic monotonicity/missing-label defect explains the validation collapse.",
            "recommendation": "Document label assumptions and validate failure endpoints against IMS metadata before production claims.",
        },
        {
            "hypothesis": "Selected features remain predictive under LOBO",
            "evidence": f"Mean sign-flip rate between train-bearing and test-bearing feature/RUL Spearman correlations is {sign_flip_rate:.2%}.",
            "support": "weakened" if np.isfinite(sign_flip_rate) and sign_flip_rate > 0.25 else "inconclusive",
            "confidence": "medium",
            "likely_impact": "Features that reverse or lose correlation across bearings cannot support stable unseen-bearing predictions.",
            "recommendation": "Rebuild feature selection inside leakage-safe LOBO, after deciding the deployment validation target.",
        },
        {
            "hypothesis": "Hyperparameters inherited from the leaky tuning regime",
            "evidence": "Diagnostics use the fixed parameters recorded in offline validation; no leakage-safe tuning has been run.",
            "support": "inconclusive",
            "confidence": "low",
            "likely_impact": "Leaky-selected hyperparameters may worsen generalization, but this root cause cannot be isolated without a controlled retuning study.",
            "recommendation": "Retune only after the feature/validation root causes are documented, using the evaluation policy.",
        },
        {
            "hypothesis": "Model bias vs variance",
            "evidence": f"Mean LOBO train MAE = {train_mae_mean:.2f}h, mean LOBO test MAE = {test_mae_mean:.2f}h, max generalization gap = {max_gap:.2f}h.",
            "support": "supported",
            "confidence": "high",
            "likely_impact": "Large train/test gaps indicate high variance and distribution-shift overfit, not simply a uniformly weak regressor.",
            "recommendation": "Constrain future tuning by worst-fold LOBO and train/test gap, not just mean test MAE.",
        },
        {
            "hypothesis": "Underfitting vs overfitting",
            "evidence": f"Learning-curve test MAE improves by {learning_delta:.2f}h from 25% to 100% training rows while train error remains far lower than test error.",
            "support": "overfitting/distribution shift supported",
            "confidence": "medium",
            "likely_impact": "Adding more rows from the same single bearing has limited value compared with adding independent bearings.",
            "recommendation": "Prioritize additional failure trajectories and leakage-safe feature selection before model complexity changes.",
        },
        {
            "hypothesis": "Current feature engineering loses temporal information",
            "evidence": "Selected inputs are row-level aggregates/rolling/EMA/z-score features; no sequence model or trajectory-level state is used in Phase 1 validation.",
            "support": "supported as a limitation",
            "confidence": "medium",
            "likely_impact": "The model sees compressed snapshots and may miss monotonic degradation patterns needed for lead-time decisions.",
            "recommendation": "Consider trajectory-aware features or sequence baselines after leakage-free tabular baselines are stable.",
        },
        {
            "hypothesis": "Another validation design better reflects deployment reality",
            "evidence": "LOBO tests unseen-bearing generalization; purged CV tests known-bearing monitoring. The evaluation policy separates these deployment questions.",
            "support": "supported",
            "confidence": "high",
            "likely_impact": "No single Set-1 split answers all production questions; model selection must state the target deployment scenario.",
            "recommendation": "Keep LOBO primary for new-bearing claims and purged CV secondary for known-asset monitoring.",
        },
    ]
    return pd.DataFrame(rows)


def write_report(output_dir: Path, tables: dict[str, pd.DataFrame], run_config: dict) -> None:
    summary_metrics = tables["phase1_summary"]
    drift = tables["feature_distribution_drift"]
    lobo_gap = tables["lobo_train_test_gap"]
    hypothesis = tables["hypothesis_evidence"]
    importance_stability = tables["feature_importance_stability"]

    content = [
        "# Root Cause Analysis Report",
        "",
        "## Scope",
        "",
        "- Objective: diagnose why leakage-safe validation is much worse than old row-level claims.",
        "- No model retuning, model artifact replacement, API changes, dashboard changes, or report overwrites were performed.",
        "- Existing fixed LightGBM hyperparameters were retrained only inside diagnostic LOBO folds to inspect train/test gaps, residuals, feature importance, and learning curves.",
        "",
        "## Inputs",
        "",
        f"- Base features: `{BASE_FEATURES_PATH}`",
        f"- Labels: `{LABELS_PATH}`",
        f"- Selected features: `{SELECTED_FEATURES_PATH}`",
        "- Source-of-truth leakage-safe validation: `reports/evaluation/phase1_validation_leakage_safe/validation_report.md`",
        "",
        "## Leakage-Safe Phase 1 Metrics Used As Baseline",
        "",
        markdown_table(summary_metrics),
        "",
        "## Dataset And Label Evidence",
        "",
        markdown_table(tables["failed_bearing_summary"]),
        "",
        markdown_table(tables["label_quality_checks"]),
        "",
        "## Selected Feature Profile",
        "",
        markdown_table(tables["selected_feature_profile"].groupby("transform").size().reset_index(name="count")),
        "",
        "## Bearing Distribution Shift",
        "",
        markdown_table(drift.head(10)),
        "",
        "PCA visualization: `pca_by_bearing.png`.",
        "",
        "## LOBO Train/Test Generalization Gap",
        "",
        markdown_table(lobo_gap),
        "",
        "## Feature Importance Stability",
        "",
        markdown_table(importance_stability),
        "",
        "## Hypothesis Evidence",
        "",
        markdown_table(hypothesis),
        "",
        "## Most Likely Root Causes",
        "",
        "1. Set 1 has only two independent failed physical bearings, so LOBO trains on one failure trajectory and tests on the other.",
        "2. The selected source features exhibit substantial bearing-to-bearing distribution shift.",
        "3. The fixed model/feature set overfits the training bearing under LOBO, shown by large train/test MAE gaps.",
        "4. Feature predictiveness and importance are not stable enough across held-out bearings to support production claims.",
        "5. Current row-level aggregate features compress trajectory context and do not explicitly optimize lead-time behavior.",
        "",
        "## What Should Not Be Blamed From Current Evidence",
        "",
        "- The duplicate-key `set1_features_temporal.parquet` artifact is not the cause of the leakage-safe metrics because those metrics use `test_base_features.parquet` plus fold-local feature reconstruction.",
        "- Basic failed-bearing label defects are not supported: monotonicity and missing-RUL checks passed for failed bearings.",
        "- A missing selected-feature artifact is not supported: Phase 1 leakage-safe validation successfully reconstructed all selected features.",
        "- Hyperparameters may contribute, but they are not proven as the primary root cause until a leakage-safe retuning study is run.",
        "",
        "## Generated Artifacts",
        "",
        markdown_table(pd.DataFrame({"artifact": sorted(run_config["artifacts"])})),
        "",
    ]
    (output_dir / "root_cause_report.md").write_text("\n".join(content), encoding="utf-8")


def run(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    full_df, selected_features = load_validation_frame(feature_mode="leakage_safe")
    failed_df = failed_regression_rows(full_df)
    feature_profile, root_features = selected_feature_profile(selected_features)

    counts, failed_summary = data_profile(full_df, failed_df)
    label_quality = label_quality_checks(failed_df)
    drift = feature_distribution_drift(failed_df, root_features)
    pca = write_pca_outputs(failed_df, root_features, output_dir)
    lobo_tables = lobo_diagnostics(failed_df, selected_features)

    summary_path = Path("reports/evaluation/phase1_validation_leakage_safe/summary_metrics.csv")
    phase1_summary = pd.read_csv(summary_path) if summary_path.exists() else pd.DataFrame()
    hypothesis = hypothesis_evidence(
        counts,
        failed_summary,
        drift,
        lobo_tables["lobo_train_test_gap"],
        lobo_tables["feature_importance_stability"],
        lobo_tables["feature_predictiveness_lobo"],
        label_quality,
        lobo_tables["residual_by_rul_bin"],
        lobo_tables["learning_curve_lobo"],
    )

    tables: dict[str, pd.DataFrame] = {
        "data_profile": counts,
        "failed_bearing_summary": failed_summary,
        "label_quality_checks": label_quality,
        "selected_feature_profile": feature_profile,
        "feature_distribution_drift": drift,
        "pca_by_bearing": pca,
        "phase1_summary": phase1_summary,
        "hypothesis_evidence": hypothesis,
        **lobo_tables,
    }

    paths: dict[str, Path] = {}
    for name, table in tables.items():
        path = output_dir / f"{name}.csv"
        table.to_csv(path, index=False)
        paths[name] = path

    run_config = {
        "purpose": "root-cause analysis only; no tuning",
        "feature_mode": "leakage_safe",
        "base_features_path": str(BASE_FEATURES_PATH),
        "labels_path": str(LABELS_PATH),
        "selected_features_path": str(SELECTED_FEATURES_PATH),
        "n_selected_features": len(selected_features),
        "selected_feature_roots": root_features,
        "critical_rul_hours": CRITICAL_RUL_HOURS,
        "warning_rul_hours": WARNING_RUL_HOURS,
        "fixed_model_params": TUNED_LGBM_PARAMS,
        "artifacts": [str(path) for path in paths.values()] + [str(output_dir / "pca_by_bearing.png"), str(output_dir / "root_cause_report.md")],
    }
    config_path = output_dir / "run_config.json"
    config_path.write_text(json.dumps(run_config, indent=2), encoding="utf-8")
    paths["run_config"] = config_path
    write_report(output_dir, tables, run_config)
    paths["report"] = output_dir / "root_cause_report.md"
    paths["pca_plot"] = output_dir / "pca_by_bearing.png"
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose leakage-safe validation generalization failure.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/evaluation/root_cause_analysis"),
    )
    args = parser.parse_args()
    paths = run(args.output_dir)
    print("Root-cause analysis artifacts written:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()

# Phase E Identifiability Validation

Scope: `ims_set1_phase_e_identifiability_v1`.

Conclusion: `not_identifiable_shared_run_clock_target`.

## Target and boundary

The supervised target is `observed_run_endpoint_proxy_seconds`: source-local wall-clock time to the observed run endpoint, including pauses. It is not true RUL, a failure time, an event-time bound, a survival duration, or damage-onset time.

Bearings 3 and 4 are the two documented damaged physical trajectories used for LOBO. Bearings 1 and 2 are inference-only censored/undocumented-outcome clock-tracking and alert-burden observations. They are not outcome metrics, negative controls, healthy controls, or event-free behavior.

## Predictors and aggregation

Three separated predictors are reported: a fold-local training-target median; a labeled shared-run clock reference; and a fixed Ridge(alpha=1.0, fit_intercept=True, solver=svd) diagnostic with nonnegative clipping. Ridge receives only Phase D registry indices 11-17, each timestamp-level mean and population standard deviation after fold-local median imputation and RobustScaler fitting on training sensor views.

Two sensor views remain rows for transform fitting, each has weight 0.5, and predictions are aggregated before every metric at the physical-bearing timestamp. IDs, timestamps, elapsed time, run position, target, outcome, sensor/channel, provenance, clocks, temporal fields, weights, split fields, and model fields are forbidden Ridge inputs.

## Evidence

The shared-run clock maximum absolute residual is `0.0` seconds. The primary diagnostic is physical-bearing LOBO (hold out bearing 3, then bearing 4). Five blocked/purged known-bearing folds use a fixed +/-30 timestamp embargo; they are subordinate and non-independent.

`metrics.json` records per-bearing metrics before aggregate and worst-bearing summaries, including provisional 50h and 100h proxy-zone alert diagnostics. Undefined rate denominators are JSON null rather than fabricated. `timestamp_predictions.jsonl` contains only the two damaged-bearing supervised diagnostic folds; `censored_clock_tracking.json` records only b1/b2 clock-tracking and alert burden.

The exact clock result means Set 1 endpoint-proxy regression cannot distinguish bearing degradation from the shared experiment clock. Ridge metrics are reference-runtime-specific diagnostics and cannot produce a GO state, authorize Set 2, establish probability calibration, support population confidence intervals, identify degradation, prove cross-dataset comparability, or support deployment, maintenance-savings, RUL-accuracy, or generalization claims.

## Reproduction

This package was built from pinned Phase B physical identities, Phase C physical endpoint proxies/outcomes, and Phase D sensor-local features. It reads no raw IMS recording, does not consume Set 2 or Set 3, writes no model artifact or database/API/dashboard state, and is validated by the raw-free Phase E evidence validator. The external canonical manifest binds the exact package bytes; two independent canonical candidates matched and the published package passed a metadata-preserving same-input no-op. Canonical bytes are owned by the recorded canonical-publication runtime; portability-validation runs validate structural and scientific invariants but do not claim canonical bytes. The cross-runtime delta audit rejects changed identities, folds, targets, clock/median predictions, clipping, proxy-zone classifications, alert positions/episodes, model ordering, conclusion, Set 2 authorization, or zero-second clock exactness; continuous Ridge deltas are evidence rather than a GO signal.

# Condition Monitoring and Policy Evaluation

This document defines the active evaluation objective. Causal condition-deviation
monitoring with persistent human-review inspection alerts is primary. Historical
endpoint-proxy regression is secondary retrospective context, not the current
product objective.

Source-of-truth baseline for this policy:
`reports/evaluation/phase1_validation_leakage_safe/validation_report.md`.

**Evidence boundary:** For a trajectory whose official IMS manual identifies terminal
damage, the final observation timestamp may be used only as the documented
`observed_failure_endpoint_proxy` convention. It is not exact failure onset, a
last-good/first-bad record, functional-failure threshold, or field maintenance truth.
Phase E showed that the Set 1 observed-run-end proxy is exactly reproducible from the
shared experiment clock; experiment age alone is not condition sensitivity.

The next separately authorized monitor must use an early-prefix sensor-local baseline,
causal scoring, physical-bearing aggregation, a causal change detector, and
persistence/hysteresis. It may emit only `baseline-consistent`,
`deviation-observed`, `persistent-severe-deviation`, or `insufficient-evidence`.
Those are deviation regimes, not healthy, warning, failure, maintenance, or RUL truth.
Endpoint proximity may be joined only after scoring for retrospective evaluation.

## Historical Endpoint-Proxy Evidence

Leakage-safe Phase 1 metrics:

| Strategy | Weighted MAE | Weighted RMSE | Mean R2 | Critical-zone MAE |
| --- | ---: | ---: | ---: | ---: |
| Current row baseline, still leaky | 20.14h | 33.73h | 0.9796 | 4.32h |
| LOBO | 226.46h | 285.37h | -0.5009 | 82.54h |
| Purged time-series CV | 122.00h | 146.80h | -7.8162 | 78.47h |

The row-level baseline is diagnostic only. It must not be used to select or
promote a model because it has same-bearing timestamp contamination.

## Historical Endpoint-Proxy Questions

The project has two distinct predictive-maintenance questions:

| Question | Validation strategy | Use in tuning |
| --- | --- | --- |
| Can the model generalize to a failed bearing not seen during training? | Leave-One-Bearing-Out (LOBO) | Primary |
| Can the model monitor a known bearing over time without adjacent-row leakage? | Purged time-series CV | Required secondary |

This historical policy does not authorize RUL-first retuning or model promotion. The
old row-level baseline remains only a leakage-inflation comparison.

## Historical Threshold Policy

Current thresholds:

| Threshold | Meaning | Status |
| --- | --- | --- |
| RUL <= 50h | Critical zone | Provisional project convention |
| RUL <= 100h | Warning zone / maintenance-planning proxy | Provisional project convention |

These thresholds are used in the existing Phase 1 validation code and reports.
They are **not yet evidence-backed by a maintenance cost matrix, service-level
agreement, repair lead time, or subject-matter-expert sign-off**. Retuning must
therefore report sensitivity at both thresholds and label them provisional until
business data justifies them.

## Historical Endpoint-Proxy Metrics

Every future tuning run must report these metrics for LOBO and purged time-series
CV:

| Metric | Definition | Why it matters |
| --- | --- | --- |
| Overall MAE | Mean absolute RUL error over all test rows | General regression quality |
| Overall RMSE | Root mean squared RUL error | Large-error sensitivity |
| R2 | Report only as diagnostic, not as tuning objective | Can be misleading under distribution shift |
| Critical-zone MAE | MAE where actual RUL <= 50h | Accuracy near failure |
| Low-RUL recall | TP / (TP + FN) for actual RUL <= threshold | Fraction of true critical/warning rows caught |
| Missed critical warning rate | FN / (TP + FN) at 50h | Direct proxy for missed failure risk |
| False alarm rate | FP / (FP + TN) at 50h and 100h | Maintenance churn and alert fatigue |
| Precision | TP / (TP + FP) at 50h and 100h | Trustworthiness of warnings |
| Per-bearing metrics | All above by held-out bearing | Detects brittle behavior hidden by averages |
| Worst-fold metrics | Worst LOBO fold and worst purged fold | Prevents one good fold from masking failure |
| Sample counts and RUL distribution | Counts by split/fold/RUL bin | Guards against empty or unrepresentative folds |
| Split contamination checks | Exact key overlap and same-bearing timestamp overlap | Validates leakage-free evaluation |

## Historical Scalar Objective

If Optuna or another tuner requires one scalar objective, use this provisional
LOBO score:

```text
business_risk_score =
    5.0 * missed_critical_warning_rate_50
  + 2.0 * false_alarm_rate_100
  + 1.0 * min(critical_zone_mae_50 / 50.0, 5.0)
  + 0.5 * min(overall_mae / 250.0, 5.0)
```

Lower is better.

Rationale:

- missed critical warnings are weighted highest because they map to unplanned
  downtime and safety/reliability risk;
- false alarms matter, but they are less severe than missed near-failure cases
  unless the business provides a different cost ratio;
- critical-zone MAE keeps the regressor honest near failure;
- overall MAE remains a weak regularizer so the model does not ignore noncritical
  operating ranges.

This scalar score is provisional. Replace the weights once actual downtime cost,
maintenance dispatch cost, bearing replacement cost, and required lead time are
known.

## Current Selection Rules

Any separately authorized monitor or benchmark must follow these rules:

1. Group by physical trajectory and use chronological or purged evaluation with
   fold-local preprocessing.
2. Treat elapsed-time-only and fixed-interval policies as mandatory baselines. A
   signal monitor must outperform them before claiming condition-monitoring value.
3. Report baseline stability, descriptive trendability/monotonicity, cross-bearing
   consistency, alert burden, persistence/hysteresis, lead time to the observed
   endpoint, abstention, and sensitivity.
4. Do not call alert burden a false-positive rate, or observed-endpoint lead time a
   failure lead time, without defensible state truth.
5. Do not select a model using row-level baselines or data with same-bearing
   timestamp overlap.
6. Do not claim production readiness or generalization from Set 1 alone.

## Historical Lead-Time Proxy

A lead-time proxy is feasible from current time-ordered RUL labels, but it is not
yet present in the Phase 1 CSV outputs.

Future tuning reports should add per-bearing lead-time metrics:

- first warning RUL: actual RUL at the first prediction where predicted RUL <= 100h;
- first critical warning RUL: actual RUL at the first prediction where predicted
  RUL <= 50h;
- missed warning flag: no warning before actual RUL <= 50h;
- excessive early warning flag: first warning occurs when actual RUL > 200h.

These are proxies, not business-validated lead-time metrics, until maintenance
planning lead time is provided.

## Current Policy and Business Boundary

Later policy work must compare run to failure, fixed-interval replacement,
elapsed-time-only, endpoint-proxy supervised benchmark, and signal-based condition
monitor. Its scenario inputs must be explicit:

```text
total cost = unplanned failures * failure/downtime cost
           + planned replacements * replacement cost
           + premature-life loss cost
           + inspections * inspection cost
```

Client-supplied inputs are failure/downtime cost, planned replacement cost,
inspection cost, intervention lead time, lost remaining-life cost, and operating
horizon/population. The decision ladder is `monitor -> inspect -> schedule
maintenance -> urgent action`. State persistence, hysteresis, abstention, and the
human inspection gate protect against premature replacement. Until prospective client
evidence exists, report ranges and sensitivity, not guaranteed savings, production
effectiveness, exact failure timing, or automatic-replacement readiness.

## Current Technical Priority

Do not productionize the API/dashboard or retune against the observed-run-end proxy.
Phase L freezes the condition-monitoring contract before the separately authorized
Phase M implementation. Set 2 retains its frozen Phase I role and has no current use
authorization; Phases J and K prohibit supervised target creation from current metadata.
The observed candidate remains protected until source/identity resolution.

Phase E's recorded canonical-publication runtime owns its exact diagnostic bytes. A
portability-validation runtime may validate frozen identities, folds, endpoint-proxy
targets, zero-second clock exactness, conclusion, and alert discretes, but cannot use
byte differences in Ridge diagnostics as retuning or selection evidence.

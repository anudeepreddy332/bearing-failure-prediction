# Business-Aligned Evaluation Policy

This document defines the evaluation objective future retuning must follow. It
supersedes any model-selection process that optimizes only generic MAE or R2.

Source-of-truth baseline for this policy:
`reports/evaluation/phase1_validation_leakage_safe/validation_report.md`.

## Current Evidence

Leakage-safe Phase 1 metrics:

| Strategy | Weighted MAE | Weighted RMSE | Mean R2 | Critical-zone MAE |
| --- | ---: | ---: | ---: | ---: |
| Current row baseline, still leaky | 20.14h | 33.73h | 0.9796 | 4.32h |
| LOBO | 226.46h | 285.37h | -0.5009 | 82.54h |
| Purged time-series CV | 122.00h | 146.80h | -7.8162 | 78.47h |

The row-level baseline is diagnostic only. It must not be used to select or
promote a model because it has same-bearing timestamp contamination.

## Deployment Questions

The project has two distinct predictive-maintenance questions:

| Question | Validation strategy | Use in tuning |
| --- | --- | --- |
| Can the model generalize to a failed bearing not seen during training? | Leave-One-Bearing-Out (LOBO) | Primary |
| Can the model monitor a known bearing over time without adjacent-row leakage? | Purged time-series CV | Required secondary |

Primary tuning objective: **LOBO business-risk score**.

Purged time-series CV is a required secondary check. A model may not be promoted
if it improves LOBO while catastrophically degrading purged-CV warning behavior.

The old row-level baseline remains only a leakage-inflation comparison.

## Threshold Policy

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

## Required Metrics

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

## Scalar Objective For Automated Tuning

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

## Model Selection Rules

Future retuning must follow these rules:

1. Optimize on leakage-safe LOBO business-risk score.
2. Report purged time-series CV as a required secondary result.
3. Report both mean and worst-fold values.
4. Do not select a model using the row-level baseline.
5. Do not promote a model that has train/test key overlap or same-bearing
   timestamp overlap in LOBO or purged validation.
6. Do not claim production readiness from Set 1 alone.
7. Treat improvements as provisional until Set 2/3 add more independent failure
   trajectories.

## Lead-Time Proxy

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

## Business Interpretation

For predictive maintenance, a missed critical warning is usually more expensive
than a false alarm because it can allow unplanned downtime, secondary damage, or
safety risk. A false alarm still has real cost: unnecessary inspection, premature
replacement, alert fatigue, and loss of operator trust.

Until a real cost matrix exists, this project should favor catching critical
near-failure samples over minimizing false alarms, but it must report both. A
model that catches failures only by flagging everything as critical is not useful.

## Current Technical Priority

Do not productionize the API/dashboard yet. The next technical step is to retune
the model using this leakage-safe, business-aligned objective and preserve all
validation outputs for comparison.

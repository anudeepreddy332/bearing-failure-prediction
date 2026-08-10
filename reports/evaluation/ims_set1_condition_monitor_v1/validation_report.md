# Phase M Condition-Monitor Validation

Scope: `ims_set1_condition_monitor_v1`.

This package is Set 1-only causal condition-deviation evidence. It is not RUL, failure-time prediction, automatic replacement, deployment, or a model-promotion claim.

The monitor uses only the seven Phase D features with registry indices 11-17, baseline-only sensor scaling, sensor-local nearest-baseline scoring, fixed 0.5/0.5 physical-bearing aggregation, and predeclared persistence/hysteresis. Initial baseline observations and incomplete two-view evidence are `insufficient-evidence`.

Endpoint proxies are absent from fitting, scoring, calibration, thresholds, states, and sensitivity. A separate post-score retrospective analysis reports lead to the observed endpoint for documented damaged bearings only; it is never failure lead time. Bearings 1/2 contribute alert burden and abstention descriptions only.

Conclusion: `condition_information_beyond_clock_not_established`. This is descriptive evidence only; Set 2, the observed candidate, targets, policy cost, and serving remain outside scope.

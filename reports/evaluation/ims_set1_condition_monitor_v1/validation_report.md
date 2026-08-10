# Phase M Condition-Monitor Validation

Scope: `ims_set1_condition_monitor_v1`.

This package is Set 1-only causal condition-deviation evidence. It is not RUL, failure-time prediction, automatic replacement, deployment, or a model-promotion claim.

The monitor uses only the seven Phase D features with registry indices 11-17, baseline-only sensor scaling, sensor-local nearest-baseline scoring, fixed 0.5/0.5 physical-bearing aggregation, and predeclared persistence/hysteresis. Initial baseline observations and incomplete two-view evidence are `insufficient-evidence`.

Endpoint proxies are absent from fitting, scoring, calibration, thresholds, states, and sensitivity. A separate post-score retrospective analysis reports lead to the authorized failure-endpoint proxy for documented damaged bearings only. This modeling convention is not damage onset, last-good/first-bad, a functional-failure threshold, or an instrumented exact physical event instant. Bearings 1/2 contribute alert burden and abstention descriptions only.

## Primary state counts

- bearing_3: {'baseline-consistent': 558, 'deviation-observed': 75, 'persistent-severe-deviation': 1235, 'insufficient-evidence': 288}; post-baseline persistent-severe fraction 0.661135.
- bearing_1: {'baseline-consistent': 587, 'deviation-observed': 138, 'persistent-severe-deviation': 1143, 'insufficient-evidence': 288}; post-baseline persistent-severe fraction 0.611884.
- bearing_4: {'baseline-consistent': 915, 'deviation-observed': 38, 'persistent-severe-deviation': 915, 'insufficient-evidence': 288}; post-baseline persistent-severe fraction 0.489829.
- bearing_2: {'baseline-consistent': 1417, 'deviation-observed': 55, 'persistent-severe-deviation': 396, 'insufficient-evidence': 288}; post-baseline persistent-severe fraction 0.211991.

## Retrospective failure-endpoint-proxy description

- bearing_3: first persistent severe 2003-11-14T15:42:17; lead to authorized failure-endpoint proxy 979059 seconds. This is not an independently observed physical event instant.
- bearing_4: first persistent severe 2003-11-17T11:02:30; lead to authorized failure-endpoint proxy 736646 seconds. This is not an independently observed physical event instant.

## Bearing 1/2 alert burden

- bearing_1: persistent-severe fraction 0.530148; alert burden only, not false-positive or healthy-control evidence.
- bearing_2: persistent-severe fraction 0.183673; alert burden only, not false-positive or healthy-control evidence.

## One-at-a-time sensitivity

- baseline_observations_144 / bearing_3: {'baseline-consistent': 12, 'deviation-observed': 5, 'persistent-severe-deviation': 1995, 'insufficient-evidence': 144}.
- baseline_observations_144 / bearing_1: {'baseline-consistent': 12, 'deviation-observed': 5, 'persistent-severe-deviation': 1995, 'insufficient-evidence': 144}.
- baseline_observations_144 / bearing_4: {'baseline-consistent': 13, 'deviation-observed': 8, 'persistent-severe-deviation': 1991, 'insufficient-evidence': 144}.
- baseline_observations_144 / bearing_2: {'baseline-consistent': 11, 'deviation-observed': 6, 'persistent-severe-deviation': 1995, 'insufficient-evidence': 144}.
- baseline_observations_576 / bearing_3: {'baseline-consistent': 1062, 'deviation-observed': 178, 'persistent-severe-deviation': 340, 'insufficient-evidence': 576}.
- baseline_observations_576 / bearing_1: {'baseline-consistent': 1278, 'deviation-observed': 130, 'persistent-severe-deviation': 172, 'insufficient-evidence': 576}.
- baseline_observations_576 / bearing_4: {'baseline-consistent': 696, 'deviation-observed': 27, 'persistent-severe-deviation': 857, 'insufficient-evidence': 576}.
- baseline_observations_576 / bearing_2: {'baseline-consistent': 1153, 'deviation-observed': 31, 'persistent-severe-deviation': 396, 'insufficient-evidence': 576}.
- neighbors_5 / bearing_3: {'baseline-consistent': 553, 'deviation-observed': 80, 'persistent-severe-deviation': 1235, 'insufficient-evidence': 288}.
- neighbors_5 / bearing_1: {'baseline-consistent': 234, 'deviation-observed': 7, 'persistent-severe-deviation': 1627, 'insufficient-evidence': 288}.
- neighbors_5 / bearing_4: {'baseline-consistent': 895, 'deviation-observed': 58, 'persistent-severe-deviation': 915, 'insufficient-evidence': 288}.
- neighbors_5 / bearing_2: {'baseline-consistent': 1401, 'deviation-observed': 35, 'persistent-severe-deviation': 432, 'insufficient-evidence': 288}.
- neighbors_20 / bearing_3: {'baseline-consistent': 553, 'deviation-observed': 80, 'persistent-severe-deviation': 1235, 'insufficient-evidence': 288}.
- neighbors_20 / bearing_1: {'baseline-consistent': 601, 'deviation-observed': 77, 'persistent-severe-deviation': 1190, 'insufficient-evidence': 288}.
- neighbors_20 / bearing_4: {'baseline-consistent': 925, 'deviation-observed': 28, 'persistent-severe-deviation': 915, 'insufficient-evidence': 288}.
- neighbors_20 / bearing_2: {'baseline-consistent': 1421, 'deviation-observed': 57, 'persistent-severe-deviation': 390, 'insufficient-evidence': 288}.
- deviation_quantile_0.975 / bearing_3: {'baseline-consistent': 518, 'deviation-observed': 115, 'persistent-severe-deviation': 1235, 'insufficient-evidence': 288}.
- deviation_quantile_0.975 / bearing_1: {'baseline-consistent': 334, 'deviation-observed': 82, 'persistent-severe-deviation': 1452, 'insufficient-evidence': 288}.
- deviation_quantile_0.975 / bearing_4: {'baseline-consistent': 754, 'deviation-observed': 169, 'persistent-severe-deviation': 945, 'insufficient-evidence': 288}.
- deviation_quantile_0.975 / bearing_2: {'baseline-consistent': 1305, 'deviation-observed': 103, 'persistent-severe-deviation': 460, 'insufficient-evidence': 288}.
- deviation_quantile_0.995 / bearing_3: {'baseline-consistent': 600, 'deviation-observed': 78, 'persistent-severe-deviation': 1190, 'insufficient-evidence': 288}.
- deviation_quantile_0.995 / bearing_1: {'baseline-consistent': 726, 'deviation-observed': 57, 'persistent-severe-deviation': 1085, 'insufficient-evidence': 288}.
- deviation_quantile_0.995 / bearing_4: {'baseline-consistent': 984, 'deviation-observed': 16, 'persistent-severe-deviation': 868, 'insufficient-evidence': 288}.
- deviation_quantile_0.995 / bearing_2: {'baseline-consistent': 1478, 'deviation-observed': 39, 'persistent-severe-deviation': 351, 'insufficient-evidence': 288}.
- persistence_observations_3 / bearing_3: {'baseline-consistent': 553, 'deviation-observed': 67, 'persistent-severe-deviation': 1248, 'insufficient-evidence': 288}.
- persistence_observations_3 / bearing_1: {'baseline-consistent': 428, 'deviation-observed': 64, 'persistent-severe-deviation': 1376, 'insufficient-evidence': 288}.
- persistence_observations_3 / bearing_4: {'baseline-consistent': 915, 'deviation-observed': 35, 'persistent-severe-deviation': 918, 'insufficient-evidence': 288}.
- persistence_observations_3 / bearing_2: {'baseline-consistent': 1402, 'deviation-observed': 31, 'persistent-severe-deviation': 435, 'insufficient-evidence': 288}.
- persistence_observations_12 / bearing_3: {'baseline-consistent': 956, 'deviation-observed': 578, 'persistent-severe-deviation': 334, 'insufficient-evidence': 288}.
- persistence_observations_12 / bearing_1: {'baseline-consistent': 602, 'deviation-observed': 211, 'persistent-severe-deviation': 1055, 'insufficient-evidence': 288}.
- persistence_observations_12 / bearing_4: {'baseline-consistent': 919, 'deviation-observed': 74, 'persistent-severe-deviation': 875, 'insufficient-evidence': 288}.
- persistence_observations_12 / bearing_2: {'baseline-consistent': 1417, 'deviation-observed': 61, 'persistent-severe-deviation': 390, 'insufficient-evidence': 288}.

**Operational instability warning:** baseline length 144 produces near-universal persistent severe states. Extensive deviation may represent condition change, experiment drift, or fragile baseline choice; it is not a promotion signal.

Conclusion: `default_no_go_clock_value_not_tested_or_established`. The clock sentinel verifies only exclusion from monitor inputs; no elapsed-time comparator was executed. This is default NO-GO evidence only: no model promotion, serving, business-value, Set 2, observed-candidate, target, or policy-cost implication.

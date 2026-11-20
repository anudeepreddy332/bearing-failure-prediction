# Phase E Cross-Runtime Delta Audit

The machine-readable record is
`ims_set1_phase_e_identifiability_v1_cross_runtime_delta_audit.json`.

Two independent canonical-publication candidates and two independent exact-pinned
Python 3.11 portability-validation candidates were byte-identical within their own
execution role. In this local comparison, aligned Ridge predictions had zero changed
rows and zero median, p95, p99, maximum absolute, and maximum relative delta. All
discrete gates were unchanged: zero clipping, 50h/100h classifications, first alert
positions, alert episodes, and Ridge/baseline MAE ordering.

The audit also requires exact identity, order, folds, targets, median and clock
predictions, conclusion, `set2_authorized=false`, and a zero-second clock oracle. It
does not make a canonical-byte claim for portability environments. Ubuntu/Python 3.11 CI
creates and retains its own portability audit under the same rules.

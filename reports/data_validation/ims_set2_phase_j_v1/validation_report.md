# Phase J Set 2 Terminal-Metadata Adjudication

## Result

`SET2_OUTCOME_METADATA_ADJUDICATED_EVENT_TIME_UNOBSERVED`

Feasibility is `NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA`.

| Bearing | Canonical status | Supported fact | Not supported |
| --- | --- | --- | --- |
| `bearing_1` | `terminal_damage_documented_event_time_unknown` | Publisher metadata documents outer-race damage by experiment end. | Exact failure time, onset, run-end equals failure, final-recording RUL zero, or an event interval. |
| `bearing_2` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |
| `bearing_3` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |
| `bearing_4` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |

The run end is only a shared experiment-clock endpoint proxy, not bearing RUL. The observed
candidate is absent from all Phase J inputs and artifacts. Phase I roles are unchanged.

## Evidence and Publication

The producer and raw-free validator pin Phase F-I tracked evidence and the approved local PDF
metadata hash. The PDF is optional at publication time and not required by CI. No raw archive,
recording name, waveform, signal distribution, feature, or candidate evidence is read.

| File | SHA-256 |
| --- | --- |
| `bearing_outcomes.jsonl` | `82acc11f9e6572fb4f3b7f08c9f30120dcf33aa5fadfa40a29a7d415a2d170ba` |
| `outcome_summary.json` | `e7a40fdd42186a356d29b0d89bb94af31c0ccc4097937e67c6a5d8d5a8119d60` |
| `evidence_manifest.json` | `7587e1923e56d646261a1d3b84b37bde7b9c19019d618e91c9eb1c22644a4f00` |

The same-input rerun returned `published=false` and preserves artifact bytes and metadata.
Event timing can be upgraded only with a bearing-linked inspection/event record; interval
timing additionally requires independently supported event-free and damaged bounds.

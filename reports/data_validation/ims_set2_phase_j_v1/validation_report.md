# Phase J Set 2 Terminal-Metadata Adjudication

## Result

`SET2_OUTCOME_METADATA_ADJUDICATED_EVENT_TIME_NOT_ESTABLISHED`

Feasibility is `NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA`.

| Bearing | Canonical status | Supported fact | Not supported |
| --- | --- | --- | --- |
| `bearing_1` | `terminal_damage_documented_event_time_unknown` | Publisher metadata documents outer-race damage by experiment end; timing is `unknown_for_documented_terminal_damage`. | Exact failure time, onset, run-end equals failure, final-recording RUL zero, or an event interval. |
| `bearing_2` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported; a terminal event is `not_adjudicable_terminal_event_not_established`. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |
| `bearing_3` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported; a terminal event is `not_adjudicable_terminal_event_not_established`. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |
| `bearing_4` | `terminal_outcome_not_reported_censoring_not_established` | No bearing-specific terminal outcome is reported; a terminal event is `not_adjudicable_terminal_event_not_established`. | Healthy, event-free, negative, right-censored, failure-free, or any exact/interval event time. |

The run end is only a shared experiment-clock endpoint proxy, not bearing RUL. No candidate
outcome, signal, label, target, feature, model, or measured-performance evidence is consumed.
The accepted Phase I role artifact, which contains the candidate's protected-role row, is only
indirectly pinned and read for role preservation. The candidate is absent from Phase J outcome
artifacts and direct outcome processing. Phase I roles are unchanged.

## Evidence and Publication

The producer and raw-free validator pin Phase F-I tracked evidence and the approved local PDF
metadata hash. The PDF is optional at publication time and not required by CI. No raw archive,
recording name, waveform, signal distribution, feature, or candidate evidence is read.

| File | SHA-256 |
| --- | --- |
| `bearing_outcomes.jsonl` | `34248fd5dad0e225aad8348b3571722449a620992a582b37ca0de4e829eb9b45` |
| `outcome_summary.json` | `eb50eec3854e9e497cad6c43a6e6d4f2c6d37b38e7a01c760ab63a436856a273` |
| `evidence_manifest.json` | `dc7b8be0be1d03f2771d3ac78a08746880325e16476d2af47dd4943e9ea2587b` |

The same-input rerun returned `published=false` and preserves artifact bytes and metadata.
Event timing can be upgraded only with a bearing-linked inspection/event record; interval
timing additionally requires independently supported event-free and damaged bounds.

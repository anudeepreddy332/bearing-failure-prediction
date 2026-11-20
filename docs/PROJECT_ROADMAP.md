# Completed research phases

The [research closeout](RESEARCH_CLOSEOUT.md) records the result after Phase N. Commit identifiers below refer to the original published evidence branch.

| Phase | Purpose | Verified status/evidence | What the phase established |
| --- | --- | --- | --- |
| A | Register Set 1 source identity | Complete: `311fb72`; `data/manifests/ims_set1/v1/recordings_manifest.jsonl` | Immutable source identity enabled canonical identities. |
| B | Build Set 1 physical identities | Complete: `597a543`; `data/canonical/ims_set1/v1/canonicalization_summary.json` | Physical recording, bearing, and sensor identities were pinned. |
| C | Record Set 1 terminal-outcome evidence | Complete: `41babf5`; `data/canonical/ims_set1_outcomes/v1/` | Endpoint proxy evidence was separated from true event-time claims. |
| D | Publish sensor-local base features | Complete: `2a9030c`; `data/canonical/ims_set1_sensor_local_base_features/v1/` | Target-independent canonical features are available. |
| E | Test Set 1 endpoint-proxy identifiability | Complete: `8f2520c`; `reports/evaluation/ims_set1_phase_e_identifiability_v1/` | Shared clock exactly explains the proxy; it cannot establish degradation. |
| F | Register local Set 2 and observed-candidate packages | Complete: `193af30`; `data/manifests/ims_sets23_source_packages/v1/` | Package identity was recorded without signal interpretation. |
| G | Establish structural identities | Complete: `64dda9e`; `data/manifests/ims_sets23_structural_identity/v3/` | Structural validity is known; observed-candidate publisher identity remains unresolved. |
| H | Record mapping evidence | Complete: `64d0f0c`; `data/manifests/ims_sets23_mapping_evidence/v1/` | Set 2 channel mapping is documented; candidate mapping remains unresolved. |
| I | Freeze dataset roles | Complete: `6197324`; `data/manifests/ims_sets23_role_freeze/v1/` | Roles preserve prior metadata awareness without authorizing use. |
| J | Adjudicate Set 2 terminal metadata | Complete: `e7cd06`; `data/manifests/ims_set2_outcome_evidence/v1/` | No supervised Set 2 target is justified from available metadata. |
| K | Search for authoritative Set 2 event evidence | Complete: `34dfc08`; `data/manifests/ims_set2_event_evidence/v1/` | No bearing-linked event time or interval was found; target creation remains prohibited. |
| L | Freeze condition-monitoring direction | Complete: `f91cfe9`; D-043 and the historical architecture | The implementation contract is integrated without authorizing serving. |
| M | Implement Set 1 causal condition monitor | Complete: `d74d5d0`; `reports/evaluation/ims_set1_condition_monitor_v1/` | Causal states were published without target fitting. |
| N | Test frozen monitor against clock references | Complete: `1fa0d21`; `reports/evaluation/ims_set1_clock_comparator_proof_v1/` | No clock-robust signal-policy claim is supported; no optimization follows. |

The earlier phases O–R proposed external validation, production controls, a prospective data contract and field evaluation. They were never undertaken and are outside this completed project. See [D-045 and D-046](decisions/DECISIONS.md#d-045--kill-the-phase-m-signal-policy-as-not-robust-beyond-the-clock) for the terminal decisions.

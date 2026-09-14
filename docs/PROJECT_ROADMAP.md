# Project Roadmap

This is the active roadmap for the repository. It freezes the direction before
any new modeling work. Historical reports, audits, and prototype code remain
available as evidence, but they do not override this document, the condition
monitoring architecture, or D-043.

## Current Direction

The primary product objective is causal condition-deviation monitoring that emits
persistent inspection alerts for human review. It can support a maintenance
decision; it cannot automatically command bearing replacement.

For a trajectory whose official IMS manual identifies terminal damage, the final
observation timestamp may be used only as the documented modeling convention
`observed_failure_endpoint_proxy`. It supports secondary retrospective benchmarks
for lead to the authorized `observed_failure_endpoint_proxy` on documented failed
trajectories. It is not exact failure onset, a last-good or
first-bad timestamp, a functional-failure threshold, or field maintenance truth.

Set 1 is development evidence. Set 2 retains its frozen Phase I role and is not
authorized for use in this phase; later external validation requires separate
authorization and the existing governance gates. The observed candidate can become
external evidence only after source and identity resolution. No current artifact
proves generalization, production readiness, maintenance savings, or exact
maintenance timing.

## Active Documentation Map

| Document | Authority |
| --- | --- |
| This roadmap | Current sequence, scope, and phase gates |
| `docs/CONDITION_MONITORING_ARCHITECTURE.md` | Current product and technical contract |
| `docs/decisions/DECISIONS.md` D-043 | Frozen direction and evidence boundary |
| `docs/EVALUATION_POLICY.md` | Current evaluation and policy-comparison rules |
| `docs/runbooks/PIPELINE_RECREATION.md` | Historical/reproducible artifact paths with a current-path notice |
| `docs/PRODUCTION_READINESS.md`, `docs/DESIGN_REVIEW.md`, historical reports | Historical snapshots and supporting evidence, not active direction |

## Phase Sequence

| Phase | Purpose | Verified status/evidence | Exit condition and why next |
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
| L | Freeze condition-monitoring direction | Complete: `f91cfe9`; D-043 and active roadmap/architecture | The implementation contract is integrated without authorizing serving. |
| M | Implement Set 1 causal condition monitor | Complete: `d74d5d0`; `reports/evaluation/ims_set1_condition_monitor_v1/` | Causal states were published without target fitting. |
| N | Test frozen monitor against clock references | Complete: `KILL_SIGNAL_POLICY_NOT_ROBUST_BEYOND_CLOCK`; `reports/evaluation/ims_set1_clock_comparator_proof_v1/` | No clock-robust signal-policy claim is supported; no optimization follows. |
| O | Perform frozen external validation | Planned, separately authorized | Consider Set 2 first; consider the observed candidate only after source/identity resolution. |
| P | Build production engineering controls | Planned, separately authorized | Require streaming feature parity, versioned inference, monitoring, rollback, and human-review workflow. |
| Q | Define prospective validation and client data contract | Planned, separately authorized | Obtain operational truth, costs, and decision ownership. |
| R | Run field pilot, calibrate, and seek deployment signoff | Planned, separately authorized | Require field evidence before any deployment decision. |

The high-impact sequence is **L -> M -> N -> O**. Serving work follows only after
evidence supports it; it is not an outcome of this documentation phase.

## Non-Negotiable Evaluation Boundary

- Thousands of recordings are repeated observations, not independent failures.
- Selection must group by physical trajectory and use chronological or purged
  evaluation with fold-local preprocessing. Random row splits are not permitted.
- Set 1 has two documented terminal failures. This limitation is irreducible:
  use simple interpretable methods, trajectory-level reporting, sensitivity
  analysis, explicit uncertainty, and later frozen external validation.
- Elapsed-time-only and fixed-interval policies are mandatory baselines. A signal
  model must outperform them under trajectory-safe evaluation before it is said
  to add condition-monitoring value. Learning experiment age alone is not enough.
- Business value is scenario/backtest evidence only. Dollar claims require explicit
  client inputs and later prospective field evidence.

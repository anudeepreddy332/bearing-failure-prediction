# Phase I Dataset-Role Freeze Validation

## Result

`ROLES_FROZEN_WITH_PRIOR_METADATA_AWARENESS`

Phase I records a role decision only. It does not inspect raw recordings, signal values,
outcomes, event times, labels, features, models, evaluation, pooling, adaptation, or serving.

| Dataset | Frozen role | Status | Current authorization |
| --- | --- | --- | --- |
| `ims_set2` | `development_evidence` | `frozen_with_prior_terminal_metadata_awareness` | none |
| `observed_4th_test_candidate_v1` | `protected_evaluation_candidate` | `unqualified_identity_mapping_unresolved_with_related_metadata_awareness` | provenance/mapping resolution only after separate authorization |

## Prior Awareness

Before role assignment, reviewers knew publisher metadata stating Set 2 ended with documented
outer-race damage in bearing 1 and documented Set 3 ended with outer-race damage in bearing 3.
The candidate's relationship to documented Set 3 remains unresolved. No signal-distribution,
degradation-pattern, event-time, label, feature, model, or measured-performance evidence was
used for role selection. Neither dataset may be described as absolutely blinded or untouched.

## Pinned Inputs

The raw-free producer and validator pin Phase F registration, Phase G structural identity, and
Phase H mapping evidence. The local PDF and raw archives are not required by CI or by this
publication. Phase H's accepted Set 2 map and unknown orientation are preserved; the candidate
mapping and publisher identity remain unresolved.

## Published Evidence

`data/manifests/ims_sets23_role_freeze/v1/` contains exactly three regular files:

| File | SHA-256 |
| --- | --- |
| `dataset_roles.jsonl` | `74f46d76cd7b167a7a930b98451b8c0ee94078982a9b1ec0767834debfa5b224` |
| `role_freeze_summary.json` | `9d9dc3a82af3c35e0407d9ab6330019cdde90fd748b85263bbc8edc56ac0be78` |
| `evidence_manifest.json` | `7e387d2edbd3fc0793bb5ac346ba2244f45698c4c56d794a52562cfba240f44a` |

The second same-input publication returned `published=false` and preserved the existing member
bytes and metadata. The raw-free validator independently enforces the two exact rows, prior
awareness disclosure, upstream pins, schemas, hashes, and affirmative-claim exclusions.

## Limits

Set 2 is not an untouched or blind external holdout, and its frozen role does not authorize
development use. The observed candidate is not a qualified holdout and cannot be used for
development, adaptation, evaluation, or outcome work. Any role change requires new evidence,
explicit authorization, and a superseding decision.

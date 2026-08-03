# Phase G Structural Identity Validation

## Result

`GO_STRUCTURAL_IDENTITY_OBSERVED_PROVENANCE_DEFERRED`

This is an outcome-blind structural result only. It permits a later, separately authorized
provenance, role, or outcome review. It does not establish a publisher dataset identity,
holdout role, damage state, failure time, censoring, exact RUL, feature compatibility,
model quality, or serving readiness.

## Inputs and method

The registered ignored archives remained local and untracked. Their Phase F byte pins are
Set 2 `b154d5ba1ae5f7f01cdd4f1bde5b08cfdc2f3134d51ad2f6614b1270a86ab632`
(85,581,092 bytes) and the source package named `3rd_test.rar`
`01e9ec83c6c55adc0300a20003a261f9a2ac2b714aae4984050325e589252bc8`
(609,047,134 bytes). The fixed 128-record chunk plan reparsed every member twice. Each
replay emitted a separate atomic receipt only after the second raw parse matched the
existing first-pass chunk and returned `published=false`. All 58 receipts were required
by assembly. The final raw-free assembly was also a strict no-op.
The repaired replay path opens each archive once with `O_NOFOLLOW`; hashing, full metadata
listing, selected-member extraction, and post-extraction rehash use that same descriptor
through `/dev/fd` with inherited descriptor handoff. Device, inode, size, mtime, ctime, and
pathname identity are checked before and after each operation.

## Structural findings

| Package identity | Recordings | Sensor observations | Timestamp range | Cadence and duplicates |
| --- | ---: | ---: | --- | --- |
| `ims_set2` | 984 | 3,936 | 2004-02-12T10:32:39 to 2004-02-19T06:22:39 | 983 ten-minute gaps; unique timestamps and bytes |
| `observed_4th_test_candidate_v1` | 6,324 | 25,296 | 2004-03-04T09:27:46 to 2004-04-18T02:42:55 | 6,315 ten-minute gaps plus eight recorded irregular gaps; unique timestamps and bytes |

All 7,308 recordings parsed as exactly 20,480 rows by 4 finite numeric columns. There
were no duplicate recording bytes within either package or across both packages. The two
timestamp ranges do not overlap, supporting separate observed runs.

Set 2 has an explicit channel 0-3 to bearing 1-4 mapping. Physical orientation is unknown.
The candidate package has no supported physical-bearing mapping. Its outer filename remains
`3rd_test.rar`, its observed inner root remains `4th_test/txt`, and the prior 4,448-recording
statement conflicts with the 6,324 observed regular files. Thus `publisher_dataset_id` is
null, publisher identity is unverified, and holdout eligibility is deferred.

## Accepted artifacts

`data/manifests/ims_sets23_structural_identity/v3/` has no raw signal values. It contains
58 canonical replay receipts and a separate 58-row coverage ledger. The ledger binds each
receipt hash, the exact first-pass chunk manifest and its hash, fixed range coverage,
Phase F/config/package pins, first-pass hashes, independently recomputed replay hashes,
and `strict_noop`. The raw-free validator recomputes the fixed 8 + 50 chunk plan, final
short-chunk endpoints, member coverage, IDs, mappings, chunk artifacts, and manifest pins.
Its hashes are:

- `recordings.jsonl`: `e5a204b0b2ec2d79e6aa91b00fe85ba8f98a97f4a621b595a4501ff979f9c3a7`
- `sensor_observations.jsonl`: `22060bbfb002c5ce6f6a449f3b9ea8cc108d84333d5132e0c06cdca514d14f98`
- `structural_summary.json`: `619cd57543127b8ab19d8b96035a43aade396352aa6cae4032149ffeb7644789`
- `chunk_replay_receipts.jsonl`: `0e255b89822c5b9699d27901ad36f5ed835a65109805bfb8c5ea620163bfc7ae`
- `chunk_replay_ledger.jsonl`: `bd4a541c3561b65d1e32f27d612b1d675088c45a304e054733f433a6f5e930e1`
- `evidence_manifest.json`: `a46fd14038c45729ddb0a47ba21af72a076a61634c51b16e27001c28d5c46387`

The unaccepted v2 duplicate package is not part of the final repository evidence. The
authoritative v3 recordings, sensor observations, and structural summary bytes did not
change during this receipt repair.

Older full candidates were retained as comparison-only evidence. Their paths, timestamps,
content hashes, sizes, ordering, and counts match the corrected package; only the authorized
candidate identity fields differ. A late earlier publication was a monitoring/session-loss
issue, not a raw-data computation failure.

## Verification

The final repair passed 23 focused Phase G tests and 436 complete DB-free tests. Ruff,
`git diff --check`, the Phase D/E/F raw-free validators, and the strengthened Phase G
validator passed. The final assembly rerun was a strict no-op, and the two independently
assembled receipt-bound candidates were byte-identical.

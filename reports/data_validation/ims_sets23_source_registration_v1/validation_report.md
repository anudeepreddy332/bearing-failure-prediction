# IMS Set 2/3 Source Registration Validation Report

## Scope and conclusion

Phase F registers source packages only. The result is **READY FOR REVIEW** as source
registration evidence, not as a signal, outcome, feature, evaluation, or model phase.
Both packages are `unconsumed`; Set 2 is only a conditional development-evidence candidate
and Set 3 is only a conditional external-holdout candidate. Neither role is frozen.

## Outer package recovery

The single discovered user-downloaded package was `/Users/anudeep/Downloads/IMS.zip`,
1,061,902,801 bytes, SHA-256
`6cb42c263b0281c725abf99f4b9fcf49915c949f31dbd2333877dc2e06ce9ec2`.
Its ZIP metadata listed ten safe members, no encryption, no absolute/traversal paths,
duplicate names, case collisions, symlinks, special members, or unsafe compression ratios.
The selected `IMS/3rd_test.rar` member was 609,047,134 bytes with CRC `99d6e111`.

Only that member was streamed into temporary staging and atomically published to the ignored
local path `data/raw/set3/3rd_test.rar`. Its SHA-256 is
`01e9ec83c6c55adc0300a20003a261f9a2ac2b714aae4984050325e589252bc8`.
Two independent one-entry source-manifest derivations agreed with manifest SHA-256
`597ba7b33ce6cf4d0bc29367e5538158751e11d48664bb30c86c444c58456ab9`.
The staged and final bytes matched. Only after those checks, the exact outer ZIP was
deleted; its local absence was verified. No other Downloads item or repository source
data was deleted.

## Preserved sources and package evidence

Set 1's existing registration manifest remains SHA-256
`f93e2f381ebeaf95d617ba1fe40c2d8ab24ca0c50f4c6887b435f30c5c960176` with 2,156
recordings. The outer `IMS/2nd_test.rar` member exactly matched the existing ignored local
`data/raw/set2/2nd_test.rar`: 85,581,092 bytes and SHA-256
`b154d5ba1ae5f7f01cdd4f1bde5b08cfdc2f3134d51ad2f6614b1270a86ab632`.
Set 2 was not imported or extracted.

The tracked registration artifacts contain two package rows and 7,311 metadata-only inner
member rows: 985 for Set 2 and 6,326 for the recovered Set 3 package. Their hashes are:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `source_packages.jsonl` | 2,306 | `290bc2b77c9b60c17b747e69163bdef719b8a6b683cff3e76f674f83f20b75d6` |
| `archive_members.jsonl` | 2,013,808 | `a9ac5751e4603f06e97eb48dff35ead71e675b0523a1a015d83dac0dc492a9f3` |
| `source_registration_summary.json` | 576 | `639bdecde01150f0aba5731f5239ec6d2c48e96e6b60f9b7e875e006b2895740` |

The Set 3 outer member name is `3rd_test.rar`, but its metadata-only inner index root is
`4th_test/txt`. This is an unresolved naming/provenance limitation. It does not establish
a role, outcome, failure event, or equivalence claim.

## Validation boundary

The registrar uses stable no-follow source hashing and `bsdtar` member metadata listing.
It does not extract or open recording payloads. The available listing tool cannot
independently establish inner-member encryption state, so that status is explicitly
`metadata_indexed_encryption_not_verified`. The raw-free validator verifies the tracked
config, schemas, hashes, order, package linkage, counts, unconsumed state, and absence of
unexpected evidence members without requiring local archives.

No Set 2/3 signals, trajectories, labels, outcomes, feature values, model inputs,
evaluations, or serving artifacts were created. Phase E's Set 1 conclusion remains
`not_identifiable_shared_run_clock_target`; `set2_authorized=false` remains unchanged.

## Verification

The focused source-registration suite collected and passed 19 tests. The complete DB-free
suite collected 408 tests and was run in bounded module groups under the isolated source
tree; every group completed without a failure. Existing preprocessing numerical warnings
remain warnings from legacy tests, not Phase F failures. `ruff check .` and
`git diff --check` passed. The Phase D and Phase E raw-free validators also passed.

The live registrar was run a second time against the local ignored source packages and
returned `published: false`. The tracked source-registration validator passed without
requiring `data/raw`, proving that CI can check the recorded evidence independently of
the developer-local archives.

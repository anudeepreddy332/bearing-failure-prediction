# IMS Set 1 Phase B Validation Report

## Scope and status

Phase B validates the registered Set 1 raw ASCII source and creates canonical physical
bearing and sensor identities. It does not create labels, windows, features, sensor
views, splits, models, database rows, serving artifacts, or Set 2 outputs.

**Final status:** complete. The tracked canonical publication passed independent
structural verification, a full strict no-op rerun, and a separate clean-build equality
check. This is a source/identity foundation result, not model evidence.

## Pinned inputs

- Phase A dataset-spec file-byte SHA-256:
  `7ed18f7585c65c2012caa543c80107d137d3727ff06b842c430f2d5c62b70181`
- Phase A dataset-spec semantic JSON SHA-256:
  `102fe1268242e4c4c0234203ded2554178a2f9d8b5206ca631ae466745c0e5af`
- Phase A recordings-manifest SHA-256:
  `f93e2f381ebeaf95d617ba1fe40c2d8ab24ca0c50f4c6887b435f30c5c960176`

## Preflight execution budget and go/no-go rule

The local workspace had approximately 143 GiB free disk before preflight. The following
budgets are explicit execution limits, not data-quality thresholds:

| Run | Runtime budget | Peak RSS budget | Additional output-disk budget |
| --- | ---: | ---: | ---: |
| 32-record read-only preflight | 120 seconds | 256 MiB | 16 MiB |
| 2,156-record full canonical build | 1,800 seconds | 512 MiB | 128 MiB |

The deterministic `ims_set1_phase_b_preflight_rank_v1` rule selects fixed manifest
indices `0`, `42`, `43`, and `2155`, then adds the 28 lowest SHA-256-ranked records by
canonical JSON containing the rule tag, recording index, and registered recording hash.

Full parsing may proceed only when every preflight hard gate passes and the measured
runtime/RSS projections fit the full-run budgets. The full parser must validate exactly
20,480 non-empty rows by eight finite numeric columns and the registered byte size and
SHA-256 from the same stable no-follow snapshot.

## Results

### Preflight

Command:

```bash
.venv/bin/python -m src.data.set1_identity --repo-root . \
  --identity-config configs/datasets/ims_set1_identity_v1.json --mode preflight
```

The final preflight used the low-RSS serial validator. It parsed 32 records and passed
all source-integrity, exact-row-count, eight-column, numeric, and finiteness gates. It
selected the required fixed indices and the following 28 deterministic hash-ranked
indices:

`132, 159, 340, 543, 564, 770, 785, 836, 876, 930, 1085, 1088, 1102, 1149, 1213,
1331, 1471, 1487, 1577, 1734, 1761, 1798, 1834, 1848, 1904, 2018, 2072, 2139`.

| Measure | Observed | Budget | Result |
| --- | ---: | ---: | --- |
| Parsed records | 32 | 32 | pass |
| Runtime | 0.4704 seconds | 120 seconds | pass |
| Peak RSS | 45.34 MiB | 256 MiB | pass |
| Conservative linear full-run runtime projection | 31.70 seconds | 1,800 seconds | pass |
| Full-run peak-RSS projection | serial process plus bounded identity rows | 512 MiB | go |
| Canonical output-disk projection | below 64 MiB from bounded JSON/JSONL identity rows with no signal arrays | 128 MiB | go |

**Go decision:** Proceed with the full parse. The projection is an execution-capacity
decision, not a data-quality claim. The full run remains fail-closed on every hard gate.

### Full validation and deterministic publication

The accepted low-RSS serial parser uses one no-follow stable file snapshot per
recording. It verifies the registered byte size and SHA-256 while validating exactly
20,480 non-empty rows by eight finite numeric columns. It uses NumPy bulk parsing after
the row/column gate; no signal array is published in canonical output. The rejected
fixed-row regular-expression experiment reached 3.27 GiB RSS during preflight and was
reverted. It is not present in the accepted parser.

| Run | Parsed | Runtime | Peak RSS | Publication result |
| --- | ---: | ---: | ---: | --- |
| Full build that created the current atomic output | 2,156 | not retained by interrupted tool capture | not retained by interrupted tool capture | published |
| Normal full rerun | 2,156 | 28.44 seconds | 82.03 MiB | strict no-op (`published: false`) |
| Clean build outside the tracked path | 2,156 | 28.01 seconds | 79.67 MiB | published, then removed after comparison |

The execution-tool interruptions occurred while capturing or waiting on long-running
commands. They were not raw-data failures and not CPU, RAM, or disk-capacity failures:
the accepted rerun completed below the 1,800-second and 512-MiB budgets, and local free
disk remained about 143 GiB.

The strict no-op comparison found all ten tracked artifact bytes, sizes, and mtimes
unchanged. The clean build under `/private/tmp` was byte-identical file-for-file and was
removed after the comparison. Disposable copies also rejected an extra artifact and a
tampered expected artifact; the tracked output was never modified for those checks.

### Canonical artifacts

| Artifact | Rows | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `dataset.json` | 1 | 291 | `5b3a793eb65ffbd3c3881aedf8faf2b68b206233314ce0130ae327b41136cbe2` |
| `run.json` | 1 | 567 | `357628ad399931b322df49649bac77646b8ef2c31e16ac1596027500d809a122` |
| `recordings.jsonl` | 2,156 | 1,038,082 | `ed8f8f63292b55bc2cdae6f2bab01abfc0b6bd7fc00e9af1acaac07df6e5a807` |
| `trajectories.jsonl` | 4 | 1,316 | `d021ec6bfed76665ab6ebe1d649e47466781ea4214265b3fb5504eea24cea88a` |
| `sensors.jsonl` | 8 | 2,480 | `be57295f9834dd2b8cbcd9c2d0ffce6bd9b365fc8ede7a991793c72a0a121f14` |
| `bearing_observations.jsonl` | 8,624 | 3,363,360 | `4ddd2e62c6d0003fad0cfbd9884a979929a361730ac3ba8f4bd9a18904087e2f` |
| `sensor_observations.jsonl` | 17,248 | 7,485,632 | `fdf52f29ac7bebec66d9b5b805439aac35ac2d65817b06ed1c4586e7ac3e7789` |
| `recording_validation.jsonl` | 2,156 | 1,066,547 | `0eb11c214709702314eae349648c80055430a1c91ec36532055f4946df067bb0` |
| `diagnostics.json` | object | 1,416 | `f3ddc7c4f647a8df33a17d936e556a9310c87e1f83cff8f908a726c3b904764e` |
| `canonicalization_summary.json` | object | 1,242 | `1ecc9aa095c4d364bb0f65bf6baf2c4f0a891192b0ea38a64f7b98e441e81361` |

The six JSONL entity files plus `dataset.json` and `run.json` contain exactly 30,198
canonical rows. Independent verification confirmed exact member names, regular
non-symlink files, summary peer hashes, schema purity, SHA-256 identity format, foreign
keys, source pins, `physical_orientation_verified=false`, and all expected
cardinalities.

## Limitations

The local raw copy is not publisher-authenticated. Timestamp timezone, hardware identity,
and physical x/y orientation remain unverified diagnostics. The canonical records do not
create labels, windows, features, sensor views, splits, models, database state, serving
artifacts, or Set 2 outputs.

# IMS Set 1 Phase C Outcome Evidence Report

## Status

Complete DB-free terminal-outcome evidence and endpoint-proxy publication. This phase
does not create true RUL, exact failure time, survival durations, sensor labels, or model
metrics.

## Pinned evidence

- Phase A manifest: `f93e2f381ebeaf95d617ba1fe40c2d8ab24ca0c50f4c6887b435f30c5c960176`
- Phase B summary: `1ecc9aa095c4d364bb0f65bf6baf2c4f0a891192b0ea38a64f7b98e441e81361`
- Metadata PDF: `data/Readme Document for IMS Bearing Data.pdf`, page 1, SHA-256
  `cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed`.

## Outcome interpretation

| Bearing | Terminal damage documentation | Damage mode | Event-time status |
| --- | --- | --- | --- |
| 1 | not documented before observation end | null | not documented; not healthy/event-free and not standard right-censored |
| 2 | not documented before observation end | null | not documented; not healthy/event-free and not standard right-censored |
| 3 | documented by experiment end | inner race defect | unknown; exact and interval fields are null |
| 4 | documented by experiment end | roller element defect | unknown; exact and interval fields are null |

## Artifacts

| Artifact | Rows | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `trajectory_outcomes.jsonl` | 4 | 2,784 | `52f56d56c84122841139928a6f3f53cbfa20ab7c2d4576a0836de95d7990b3d7` |
| `bearing_observation_endpoint_proxies.jsonl` | 8,624 | 4,298,044 | `a61c618d73ec66f554fa89ff53017439405f8eb21c9e32f3f48c9c0def5f010f` |
| `label_diagnostics.json` | object | 258 | `f4308ebd99a402790423eed56c2f39350709708624cd1bee21fc5bf2fc644974` |
| `labeling_summary.json` | object | 618 | `9cda60864f796aae65008ac00fa8ca15613cccab0bf25a519343303a7ff981ea` |

The proxy is `ims_set1_observed_run_endpoint_proxy_v1`: naive source-local wall-clock
seconds to the observed run endpoint, including pauses. It is permitted only for
historical failed-bearing endpoint-proxy diagnostics under separately authorized work.
The 4,312 b3/b4 proxy rows represent two physical trajectories, not 4,312 events.
There are zero sensor proxies, exact event timestamps, or event-time interval bounds.

## Determinism and integrity checks

The normal command completed as a strict no-op against the tracked publication
(`published: false`). A separate clean build outside the tracked output was
byte-identical file-for-file and then removed. Disposable copies rejected both an
unexpected output member and a byte-tampered artifact; the tracked publication was
not modified during either check.

## Contract-test coverage

The focused Phase C suite now contains 21 tests. It covers exact config, schema,
nullable-field, scientific-outcome, fixed-proxy-contract, and known-ID contracts; a
synthetic four-trajectory, irregular-wall-clock build; Phase B observation/sensor
natural-key, cardinality, and foreign-key failures; output no-op and malformed-output
rejection; and CLI failure for invalid config. The synthetic test uses no raw signals or
tracked canonical output. This is focused contract coverage, not an exhaustive proof of
all filesystem races or all possible corruptions of Phase B artifacts.

## Cold-clone evidence verification correction

The prior unit-test contract mixed pure outcome-config validation with verification of
the developer-local metadata PDF. The PDF is intentionally not repository-tracked, so a
clean checkout could not run ordinary config tests even though the publication contract
was correct. The implementation now separates `_validate_config(config_path)`, which
reads only the declarative configuration and validates its schema, scientific contract,
safe relative path, and SHA-256 shape, from `_verify_metadata_evidence(repo_root, cfg)`.
The latter retains the stable no-follow reader and mandatory byte-for-byte PDF pin before
any Phase B load, row construction, output creation, or no-op acceptance.

The committed publication evidence contract is unchanged: evidence ID
`ims_metadata_pdf_set1_terminal_damage_v1`, path
`data/Readme Document for IMS Bearing Data.pdf`, page 1, classification
`publisher_metadata_terminal_damage_documented_by_experiment_end`, and SHA-256
`cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed`.
The PDF is neither claimed redistributable nor repository-tracked. Permanent tests use
synthetic bytes under temporary directories for matching, missing, substituted,
symlinked, and non-regular evidence cases. They also prove absent evidence stops the
build before Phase B loading and preserves absent or existing outputs; the CLI fails
nonzero without publication.

In an isolated source snapshot without the PDF, the focused Phase C suite collected 31
tests and the full DB-free suite collected 101 tests; both passed. A fresh Python 3.11.15
PDF-free snapshot imported `src.data.set1_outcomes` from its own corrected source tree,
then passed the base Ruff command and verbose 101-test pytest command using the already
proven dependency environment. A separate focused run also passed with a synthetic file
present at the configured evidence path; the guarded reader test proved pure config
validation did not open that file.

Final publication-time evidence used the hotfix source worktree as the child current
working directory and recorded its resolved module path and source SHA-256
`e56e0a1aae7334baf083d8e962357e61205fd04b4f21b978327c83482efeada7`.
Against the original local repository root where the pinned PDF exists, that monitored
producer invocation returned zero with empty stderr and `published: false`. It preserved
the canonical directory/member device, inode, mode, size, nanosecond mtime, bytes,
hashes, and member set. The earlier monitored no-op is retained as historical support but
was not used as final source-origin proof because it did not record child cwd/module
origin. Temporary review evidence is at
`/private/tmp/ims_set1_phase_c_ci_hotfix_final_noop_v2.ukFsXd`,
`/private/tmp/ims_set1_phase_c_ci_snapshot_corrected.CznQuB`, and
`/private/tmp/ims_set1_phase_c_ci_evidence_present.HP3bdT`.

No outcome/proxy science, configuration values, canonical artifact hashes, or decision
record changed in this correction.

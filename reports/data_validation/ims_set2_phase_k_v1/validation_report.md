# Phase K Set 2 Event-Evidence Search

## Result

`NO_GO_NO_NEW_AUTHORITATIVE_EVENT_EVIDENCE`

Set 2 target creation remains `NO_GO_SUPERVISED_TARGET_FROM_AVAILABLE_METADATA`.

## Finite Primary Search

1. Page 2 of the hash-pinned local producer readme, `cf46d37c21f7f292c11bbbdd4695d876c417ed1d6425e3d87c962ae2182ae6ed`, says Set 2 was a test-to-failure experiment and that outer race failure occurred in bearing 1 at the end of the experiment. It does not bind failure to the final recording timestamp or establish an event-free lower bound or interval.
2. The official [NASA IMS catalog](https://data.nasa.gov/dataset/ims-bearings) identifies IMS University of Cincinnati provenance, but no Set 2 bearing event record.
3. Qiu, Lee, Lin, and Yu (2006), DOI `10.1016/j.jsv.2005.03.007`, was located as experiment-author publication metadata only. No retrieved primary full text establishes Set 2, bearing, and timing linkage.

## Secondary Discovery

This was a finite bounded scan, not proof that no relevant work exists anywhere. The registry records: Hongru Li, Yaolong Li, and He Yu's 2019 *A Novel Health Indicator Based on Cointegration for Rolling Bearings' Run-To-Failure Process*; the inaccessible 2021 DOI `10.1155/2021/6806319`; the pinned `48094546c0a4366f3add4aeb88fbe5929b7b0cf6` README of Miltos-90's `Failure_Classification_of_Bearings` repository; Martin Kasala's 2026 *IMS Bearing Early-Warning Benchmark*; and an inaccessible Kaggle discovery query. The repository README describes Set 1 only. The accessible Set 2 papers and benchmark repeat terminal-damage, run-end, derived-score, or label-construction context. None led to a new independently retrieved primary event record. Any apparent failure-at-end, RUL countdown, alert threshold, row-level methodology, or same-bearing split implication remains discovery context, not event evidence.

## Adjudication

Bearing 1 remains documented terminal damage with timing unknown. Bearings 2-4 remain terminal event not established; no censoring is inferred. No exact timestamp or interval is recorded. A future timing upgrade requires a specifically identified primary inspection, teardown, test, or event record, followed by separate semantic acceptance.

## Artifact Hashes

| File | SHA-256 |
| --- | --- |
| `source_registry.jsonl` | `4cb59391b9825ab490ba2a6a69933c3dd47c321dcffe6b7f676a0c6f8f971ee7` |
| `evidence_findings.jsonl` | `86dd2aafc55c2657741a08030c7cee4c26be21a8bd174dd166540ec90efaa353` |
| `secondary_ml_evidence_registry.jsonl` | `4850594fa0c479d9b2d1db0927e558dea1833b6ee9345b6f6d11913005267d7d` |
| `adjudication_summary.json` | `f32df20c85bee039a762dd3dda1fe85cd4ffc5aa63e9ad773f46660b83547242` |
| `evidence_manifest.json` | `b66d770394e4c8259b47916d998342a68f66c22dbd17731b8463bf2c0bc693c5` |

# IMS bearing vibration and failure-prediction research

This completed case study follows a bearing-life regression prototype through an evaluation correction, a label audit, and a causal condition-monitoring experiment. I built Python vibration feature pipelines, a Postgres and LightGBM prototype with Streamlit and FastAPI interfaces, and a separate database-free evidence pipeline with versioned manifests, physical bearing and sensor identities, and reproducible checks.

## Data scale

IMS Set 1 recorded four physical bearings together on one test rig. There were **2,156 recordings** with **20,480 samples per channel at 20,000 Hz** across eight channels. That is about **1.024 seconds per recording**, **353,239,040 scalar vibration readings**, **17,248 sensor-observation rows**, and **8,624 physical-bearing timestamps** across four trajectories. The observation span was **827.56 wall-clock hours**, including gaps. The raw amplitude calibration and timestamp timezone are unverified. Terminal damage was documented for bearings 3 and 4. The available record leaves bearing-specific event timing and standard censoring unestablished.

## What the experiments established

| Question | Result | Scope |
| --- | --- | --- |
| Would the original LightGBM approach transfer to a different bearing? | Mean absolute error (MAE) was **226.46 h** after rebuilding transforms within each fold. Bearing 3 was **206.89 h** and bearing 4 was **246.02 h**. | Two leave-one-bearing-out folds, each training on one documented damaged trajectory and testing on 4,312 sensor-observation rows from the other. The inherited model settings and feature list make this a historical diagnostic. |
| How did it perform on withheld time blocks from the same bearings? | Row-weighted MAE was **122.00 h** across five purged blocks. | 8,624 evaluated sensor-observation rows across the same two bearings. Training can include observations later than a held-out block, so prospective performance remains unmeasured. |
| What did the regression target measure? | A shared-run clock reconstructed the **run-end proxy to 0 seconds maximum absolute error**. | Two same-run damaged bearings, 4,312 held-out physical-bearing timestamps in total under leave-one-bearing-out. The countdown ends at the last observation. Physical failure time remains unknown. |
| Did a causal vibration monitor establish value beyond elapsed time? | Its persistent-alert state differed from the common elapsed-time schedule at **4,311 of 8,624 matched physical-bearing timestamps**. Burden ordering changed in **6 of 8** sensitivity variants, and onset ordering was unverified in **all 8**. | Four Set 1 trajectories. A separate fixed-interval reference counted 13 scheduled inspections per bearing. The predeclared gate failed and the policy was retired. |

The original 80/20 split shuffled sensor-observation rows within target bins, letting the same bearings and even opposite axes of the same physical timestamp cross the split. Temporal history, full-series normalization, and same-timestamp cross-axis features had already been computed. The original tuning and final evaluation used the same test partition by design.

The project ended at the Phase N no-go decision. Set 2 established terminal damage metadata without an event-time target, and the package with the `4th_test/txt` inner root remained an unresolved candidate. The findings support the evaluation and evidence engineering described here. Deployment, maintenance decisions, and savings are outside the demonstrated scope.

- [Research closeout, claims ledger, dataset inventory, and verification](docs/RESEARCH_CLOSEOUT.md)
- [Historical archive and retained prototype evidence](docs/archive/README.md)
- [License](LICENSE)

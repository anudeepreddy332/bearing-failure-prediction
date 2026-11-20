# Repository guidance

This repository is a completed IMS bearing vibration research case study. The [closeout](docs/RESEARCH_CLOSEOUT.md) is the public evidence summary. The [phase map](docs/PROJECT_ROADMAP.md), [archive index](docs/archive/README.md) and [decision log](docs/decisions/DECISIONS.md) preserve the research trail. D-045 rejected the frozen signal policy and D-046 closes the project.

- Preserve published evidence, original labels where part of an archived artifact, and manifest-pinned bytes and paths. Write reproduction outputs to temporary directories.
- Set 1 comprises one shared run of four physical bearings. Bearings 3 and 4 have documented terminal damage with unknown event times. Bearings 1 and 2 lack documented terminal damage. Standard right censoring is unestablished. The elapsed-time target is a run-end proxy.
- The legacy model, FastAPI, database and Streamlit code are historical prototypes. Phase 1's row split is a diagnostic of leakage. Physical trajectories are the grouping unit. The Phase 1 blocked CV uses held-out blocks with a purge and can train later than test observations.
- Set 2 outcome work ended without an event-time target. The observed `4th_test/txt` package has unresolved publisher identity and physical mapping. External data work, new labels, experiments, pooling, tuning, policy design, serving and deployment are outside the completed study.
- Before touching published evidence, read the [evaluation record](docs/EVALUATION_POLICY.md), [monitor architecture](docs/CONDITION_MONITORING_ARCHITECTURE.md), the [outcome report](reports/data_validation/ims_set1_phase_c_v1/validation_report.md), and the relevant decision and artifact.

Use Python 3.11 and the installation constraint in [CI](.github/workflows/ci.yml). Run `ruff check .` and `pytest tests/ -q -p no:cacheprovider`. Follow CI's raw-free validators and write builds to temporary directories. Phase E canonical validation verifies the frozen bytes. A portability rebuild independently verifies scientific and structural invariants. The focused DB-free suite provides no end-to-end live database or serving verification.

Keep raw signals, developer-local metadata and notebooks, database runtime files, private notes, model pickle files, and credentials out of commits and pull requests. The [legacy recreation runbook](docs/runbooks/PIPELINE_RECREATION.md) records the two historical pipeline generations and their missing inputs.

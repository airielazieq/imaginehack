# Mock Data Generator & Controller

Synthetic cloud telemetry + live demo controller (ARCHITECTURE.md §10).
Because there's no access to real HILTI cloud systems, this drives the whole
demo with controllable synthetic signals.

## Files

```
data/
  sample_workloads.json                  # 8-workload registry (§10.3)
  healthy_telemetry_baseline.json        # healthy snapshot per workload (§10.4)
  scenario_payloads.json                 # 6 demo scenario patches + expected outcomes (§10.5)
  historical_telemetry_training_data.csv # 960 rows for IF + XGBoost (§8.9, §10.9)
  metric_baselines.json                  # per-workload threshold baselines (§6.11, generated)
generate_historical.py                   # (re)generate the CSV + metric_baselines.json
streams/generator.py                     # telemetry generation functions
controllers/controller.py                # stateful controller (trigger / reset / stream)
```

The FastAPI surface lives at the repo root in `../mock_api.py` (the
`mock-data-generator` directory name contains a hyphen and can't be imported as
a Python package, so the controller/generator are loaded by path).

## Controller API (§11.9)

| Method | Endpoint | Purpose |
|---|---|---|
| GET  | `/api/mock/scenarios` | List the 6 demo scenarios |
| POST | `/api/mock/trigger/{scenario_id}` | Apply a scenario patch + ingest it |
| POST | `/api/mock/reset` | Clear scenarios, push healthy telemetry for all (§10.7) |
| POST | `/api/mock/stream/start` | Start the continuous 3s stream (§10.6) |
| POST | `/api/mock/stream/stop` | Stop the stream |
| GET  | `/api/mock/status` | Streaming flag, active scenarios, interval, ingest URL |

Run standalone (for local testing without the SE backend):

```bash
python mock_api.py            # serves on http://localhost:8001
```

Config via env vars:
- `MOCK_INGEST_URL` (default `http://localhost:8000/api/telemetry/ingest`)
- `MOCK_STREAM_INTERVAL` seconds (default `3.0`)

The stream tolerates an unreachable backend (it logs nothing and keeps going),
so you can exercise the controller before the SE API is up.

## Demo scenarios & expected behavior

Each scenario is a telemetry **patch** applied on top of a workload's healthy
baseline. The `expected` block in `scenario_payloads.json` is the contract the
deterministic pipeline must satisfy (verified by `tests/validate_scenarios.py`).

| Trigger | Target workload | Issue type | Severity | Execution mode |
|---|---|---|---|---|
| `trigger_idle_dev_server` | BIM Processing Engine | idle_or_overprovisioned_workload | medium | **auto_fix** |
| `trigger_public_storage_exposure` | Project Document Storage | public_storage | critical | **human_escalation_required** |
| `trigger_critical_production_vulnerability` | Field Reporting App API | critical_exposed_vulnerability | critical | **human_escalation_required** |
| `trigger_carbon_heavy_batch_job` | Monthly Progress Report Generator | carbon_heavy_workload | medium | user_approval_required |
| `trigger_missing_monitoring` | Deployment CI/CD Pipeline | no_monitoring | medium | auto_fix |
| `trigger_cost_spike` | Legacy Analytics VM | cost_spike_or_waste | medium | auto_fix |

### Suggested live demo order (§14.2)
1. Show healthy dashboard → `POST /api/mock/reset`, then `stream/start`.
2. `trigger_idle_dev_server` → detection, explanation, NBA, savings, auto-fix.
3. `trigger_public_storage_exposure` → approval/escalation (no blind auto-fix).
4. `trigger_carbon_heavy_batch_job` → projected carbon reduction.
5. Show audit log / governance, close with measurable outcomes.

## Regenerating data

```bash
python mock-data-generator/generate_historical.py   # rewrites CSV + metric_baselines.json
python -m ml.train_all                               # retrain on the new data
python tests/validate_scenarios.py                   # re-validate triggers still fire
```

Seeded with `SEED = 42` for reproducibility.

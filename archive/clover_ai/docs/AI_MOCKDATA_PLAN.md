# AI / Mock Data Subteam — Implementation Plan

**Project:** CloudGuard GreenOps (ImagineHack 2026, Track 2 / HILTI)
**Owner:** AI / Mock Data Subteam
**Source of truth:** [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — section references below (e.g. §9.2) point into it.
**Backend stack (confirmed):** Python / FastAPI. ML and the mock generator run **in-process** with the backend — no separate microservice needed.

---

## 1. Scope — what this subteam owns

From ARCHITECTURE §15.2 and §10.10, we own everything that produces or reasons about data:

- Synthetic telemetry (workloads, healthy baselines, historical training data, scenario payloads)
- The live mock data generator + controller API
- Isolation Forest anomaly detection (§5.5.1, §8.2)
- XGBoost forecasting + optimization impact forecast (§8.6–8.12)
- SHAP / SHAP-style explanations (§5.6, §8.5)
- LLM explanation **payloads** and fallback templates (§5.6.2, §5.9, §8.13)
- Rule-based issue classification (§5.5.2) and its merge logic (§6.6)

**Not ours** (Software Engineering subteam): web app, REST API plumbing, storage, UI pages, the mock-controller *UI*.

### The contract boundary
Our interface to the SE team is the **JSON objects in ARCHITECTURE §9**. These schemas are non-negotiable — honor them field-for-field:

- §9.1 Cloud Workload Telemetry (our output → their ingest)
- §9.2 Structured Issue Object (our Detection output)
- §9.3 Structured Recommendation Object (our NBA output)
- §9.5 Remediation Result references our forecast numbers

---

## 2. Decisions to lock before coding

| # | Decision | Default / status | Owner |
|---|---|---|---|
| D1 | Currency = **RM** across all forecast/savings numbers (§B.3) | Confirm with team | Pitch + us |
| D2 | Rule merge: idle/cost vs carbon merge into ONE primary action (§6.6) | Per spec — bake into scenario data | Us |
| D3 | Thresholds = `baseline(workload, metric) × multiplier(metric)` (§6.11) | We compute baselines; domain expert sets multipliers | Us + domain |
| D4 | Isolation Forest is **trained once and frozen for the demo** (§8.14) | Per spec — no live retraining | Us |

---

## 3. Deliverables checklist (§10.10)

- [ ] `mock-data-generator/data/sample_workloads.json`
- [ ] `mock-data-generator/data/healthy_telemetry_baseline.json`
- [ ] `mock-data-generator/data/historical_telemetry_training_data.csv`
- [ ] `mock-data-generator/data/scenario_payloads.json`
- [ ] `mock-data-generator/` service (4 modes: baseline / scenario / reset / stream)
- [ ] Mock controller API endpoints (§11.9) — UI is SE's
- [ ] `rules/detection_rules.json`, `rules/recommendation_rules.json` (thresholds + multipliers)
- [ ] `ml/isolation_forest/` — trained, frozen model + inference
- [ ] `ml/xgboost_forecast/` — 3 regressors + optimization impact
- [ ] `ml/explainability/` — SHAP-style top factors
- [ ] LLM payload builders + fallback templates
- [ ] Trigger-behavior documentation

---

## 4. Sequenced steps

Build the **data backbone first**, then layer ML on top. Each step is gated so the SE team is never blocked on our ML.

### Step 0 — Setup & decisions (~0.5 day)
- [ ] Create `/mock-data-generator` and `/ml` per ARCHITECTURE §15.3.
- [ ] Python env: `scikit-learn`, `xgboost`, `shap`, `pandas`, `numpy` (pin in `requirements.txt`).
- [ ] Resolve D1–D4 above.
- [ ] Agree `/rules/*.json` shape with SE (config-driven thresholds, §6.11).

### Step 1 — Static data deliverables → unblocks SE **Phase 1**
No ML required; SE can load these immediately.
- [ ] `sample_workloads.json` — 8 workloads (§10.3), full §9.1 schema.
- [ ] `healthy_telemetry_baseline.json` — one healthy snapshot per workload (§10.4 template).
  - **Critical:** baselines must be normal enough that the trained Isolation Forest does NOT flag them. Design these together with the scenarios (Step 1c).
- [ ] `scenario_payloads.json` — 6 scenarios (§10.5) as telemetry patches keyed by trigger id (`trigger_idle_dev_server`, `trigger_public_storage_exposure`, `trigger_critical_production_vulnerability`, `trigger_carbon_heavy_batch_job`, `trigger_missing_monitoring`, `trigger_cost_spike`).

### Step 2 — Historical training data → unblocks ML
- [ ] `historical_telemetry_training_data.csv` — 50–200 rows/workload (§10.8), `target_*_30d` via §8.9 noise formulas (noise 0.85–1.20).
  - Feeds **both** Isolation Forest (normal baseline) and XGBoost (regression targets).
- [ ] Compute per-workload `baseline(workload, metric)` from this CSV → write into `/rules/*.json` for §6.11 thresholds.

### Step 3 — Mock generator + controller API → unblocks SE **Phase 5** / live demo
- [ ] Generator service with 4 modes (§4.6, §10.6): healthy stream, triggered scenario, reset, continuous 3s stream → POSTs `/api/telemetry/ingest`.
- [ ] Controller endpoints (§11.9): `GET /api/mock/scenarios`, `POST /api/mock/trigger/:id`, `POST /api/mock/reset`, `POST /api/mock/stream/start|stop`, `GET /api/mock/status`.
- [ ] Reset behavior (§10.7): clear scenario flags, send healthy telemetry, reset heatmap to green.
- [ ] Trigger-behavior docs.

### Step 4 — ML: Detection → unblocks SE **Phase 2**
- [ ] Isolation Forest on §8.4 feature set; train once, **freeze** (§8.14). Output `{model_name, anomaly_score, is_anomaly}`.
- [ ] Feature preprocessing/encoding (categorical → `*_encoded` per §8.4).
- [ ] Rule-based issue classifier — 7 rules (§5.5.2) mapping anomaly → typed issue.
- [ ] Merge logic (§6.6): multiple matched rules → one primary + contributing rules; security ≠ cost never merge.
- [ ] SHAP-style top-3 contributing factors (§5.6.1, §8.5) — framed as contribution, never causation.
- [ ] Severity logic (§5.8).
- [ ] Emit full **Structured Issue Object** (§9.2) including `confidence_score`, `estimated_impact`, `detected_evidence`.
- [ ] Fallback: `model_name = "fallback_rules_only"` if model fails (§5.9).

### Step 5 — ML: Forecast → unblocks SE **Phase 3**
- [ ] XGBoost: 3 regressors (or multi-output) for cost/energy/carbon 30d (§8.7–8.8).
- [ ] Optimization impact forecast via §8.11 canonical factor table → forecast_without_action / after_action / projected_savings (§8.12).
- [ ] Fallback: `model_name = "deterministic_forecast_fallback"` (§8.13).

### Step 6 — LLM explanation payloads
- [ ] Issue-explanation payload builder (§5.6.2) and recommendation-explanation payload.
- [ ] Fallback templates (§5.9, §8.13) for when LLM is unavailable.
- [ ] Handoff: confirm with SE whether the LLM **call** lives in our module or their backend; we own the payload shape + templates either way.

---

## 5. Non-negotiable demo outcomes

Detection is deterministic (§3.2), so our scenario data must **force** the correct path. Verify each:

| Scenario | Target workload | Must result in |
|---|---|---|
| Idle dev server | `wl-bim-processor-001` | overprovisioned → **auto-fix** (low-risk, reversible) |
| Public storage exposure | `wl-doc-storage-001` | security issue → **approval/escalation, never auto-fix** (§13.5) |
| Critical prod vulnerability | `wl-field-app-001` | critical → **human escalation** (AI never auto-patches prod) |
| Carbon-heavy batch job | `wl-report-generator-001` | carbon issue → reschedule/resize, projected carbon reduction shown |
| Missing monitoring | `wl-ci-pipeline-001` | enable monitoring / auto-ticket |
| Cost spike | `wl-costly-vm-001` | resize/shutdown, savings forecast |

**Before the live demo:** because thresholds are now data-derived (§6.11), re-validate every scenario still fires the intended issue type + severity (§6.11 action item).

---

## 6. Risks & mitigations (our slice of §15.7)

| Risk | Mitigation |
|---|---|
| ML training overruns | Ship fallback rules + template explanations first (§5.9, §8.13); models are upgrades, not blockers |
| Frozen model flags a healthy baseline | Co-design baselines + scenarios; dry-run Isolation Forest on all 8 healthy snapshots, expect `is_anomaly=false` |
| Live stream breaks mid-demo | Manual scenario trigger path must work standalone (§10.6 manual mode) |
| LLM unavailable | Template fallbacks; never block the flow on an LLM call |
| Scenario doesn't trigger after threshold change | Re-validation gate in §5 before demo |

---

## 7. Definition of done (this subteam)

- [ ] All 7 §10.10 deliverables exist and load.
- [ ] Mock controller can trigger all 6 scenarios + reset + stream.
- [ ] Isolation Forest produces stable anomaly scores (frozen) across repeated runs.
- [ ] Every scenario yields the correct Structured Issue Object (§9.2) and forecast (§8.12).
- [ ] The three "non-negotiable" safety outcomes in §5 hold every run.
- [ ] Fallbacks verified by deliberately disabling the ML model and the LLM.

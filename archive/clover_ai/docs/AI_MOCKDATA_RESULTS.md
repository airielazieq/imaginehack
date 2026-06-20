# AI / Mock Data Subteam — Results Report

**Project:** CloudGuard GreenOps — Secure & Energy-Aware Cloud Intelligence Platform
**Context:** ImagineHack 2026, Track 2 (HILTI)
**Subteam:** AI / Mock Data
**Status:** ✅ Complete — all deliverables built, models trained, pipeline validated
**Spec reference:** [`../ARCHITECTURE.md`](../ARCHITECTURE.md) · **Plan:** [`AI_MOCKDATA_PLAN.md`](AI_MOCKDATA_PLAN.md)

---

## 1. Executive summary

The AI / Mock Data subteam scope is **complete and verified end-to-end**. We delivered
synthetic telemetry, a live mock controller, the ML detection + forecast models,
SHAP-style explainability, and LLM explanation payloads — all conforming to the
data contracts in `ARCHITECTURE.md` §9.

A single automated gate (`tests/validate_scenarios.py`) confirms the whole
detect → recommend pipeline behaves correctly and deterministically:

- **6 / 6** demo scenarios produce the correct issue type, category, severity, and execution mode.
- **8 / 8** healthy workloads stay clean (no false alarms from the frozen model).
- **3 / 3** non-negotiable safety outcomes hold (auto-fix vs. approval vs. escalation).

**Backend stack:** Python / FastAPI — ML runs in-process; no separate service.

---

## 2. Deliverables (vs. ARCHITECTURE §10.10)

| # | Required deliverable | Status | Location |
|---|---|---|---|
| 1 | `sample_workloads.json` | ✅ | `mock-data-generator/data/` |
| 2 | `healthy_telemetry_baseline.json` | ✅ | `mock-data-generator/data/` |
| 3 | `historical_telemetry_training_data.csv` | ✅ 960 rows | `mock-data-generator/data/` |
| 4 | `scenario_payloads.json` | ✅ 6 scenarios | `mock-data-generator/data/` |
| 5 | Mock data generator service | ✅ | `mock-data-generator/streams/`, `controllers/` |
| 6 | Mock controller (API endpoints) | ✅ §11.9 | `mock_api.py` |
| 7 | Trigger-behavior documentation | ✅ | `mock-data-generator/README.md` |

**Beyond the minimum**, we also delivered the ML/AI components from §15.2:
Isolation Forest (frozen), 3× XGBoost forecasters, SHAP-style explainability,
rule-based issue classifier + NBA recommender, LLM payloads + fallbacks, the
threshold-config rules files, and a validation harness.

---

## 3. Models trained

All trained on the 960-row synthetic historical dataset (120 rows × 8 workloads).

| Model | Purpose | Spec | Result |
|---|---|---|---|
| Isolation Forest | Anomaly detection | §5.5.1, §8.14 | Trained on 19 features, **frozen** for demo |
| XGBoost — cost_30d | Cost forecast | §8.7 | Train MAPE ≈ **4.0%** |
| XGBoost — energy_30d | Energy forecast | §8.7 | Train MAPE ≈ **4.0%** |
| XGBoost — carbon_30d | Carbon forecast | §8.7 | Train MAPE ≈ **3.9%** |

Artifacts saved to `ml/artifacts/` (`.joblib`), committed so the SE team gets
working models without retraining. Rebuild any time with `python -m ml.train_all`.

> **Note on MAPE:** these are *training* errors on synthetic data and are expected
> to be low. They demonstrate the model fits the generated targets correctly; they
> are **not** a claim of real-world forecast accuracy. The MVP honestly frames
> XGBoost as trained on synthetic telemetry (§8.6).

---

## 4. Validation results

Command: `python tests/validate_scenarios.py` → **exit 0 (ALL CHECKS PASSED)**

### 4.1 Scenario detection + recommendation

| Scenario | Target workload | Issue type | Severity | Exec mode | Anomaly | Conf. | Projected savings (cost / carbon) |
|---|---|---|---|---|---|---|---|
| Idle dev server | BIM Processing Engine | idle_or_overprovisioned_workload | medium | **auto_fix** | ✓ | 0.94 | RM 1,182.63 / 344.37 kgCO₂e |
| Public storage exposure | Project Document Storage | public_storage | critical | **human_escalation** | – | 0.70 | — (security) |
| Critical prod vulnerability | Field Reporting App API | critical_exposed_vulnerability | critical | **human_escalation** | – | 0.70 | — (security) |
| Carbon-heavy batch job | Monthly Progress Report Generator | carbon_heavy_workload | medium | user_approval | ✓ | 0.90 | RM 484.64 / 306.75 kgCO₂e |
| Missing monitoring | Deployment CI/CD Pipeline | no_monitoring | medium | auto_fix | – | 0.70 | — (enable monitoring) |
| Cost spike | Legacy Analytics VM | cost_spike_or_waste | medium | auto_fix | ✓ | 0.90 | RM 1,267.48 / 436.14 kgCO₂e |

Every row matched the `expected` contract in `scenario_payloads.json` exactly
(issue_type, issue_category, severity, execution_mode).

> Security scenarios show `anomaly = –` because they are caught by deterministic
> security rules (public storage / critical vuln), not by the statistical model —
> exactly as designed (§5.5.2: rules classify, the model only flags abnormality).
> Savings are not applicable to security fixes (§6.9), shown as `RM 0`.

### 4.2 Healthy baselines (must NOT be flagged)

All 8 workloads passed — the frozen Isolation Forest produces **zero false positives**
on normal telemetry:

```
[OK] wl-field-app-001     [OK] wl-iot-dashboard-001   [OK] wl-bim-processor-001
[OK] wl-doc-storage-001   [OK] wl-report-generator-001 [OK] wl-ci-pipeline-001
[OK] wl-costly-vm-001     [OK] wl-site-db-001
```

### 4.3 Non-negotiable safety outcomes (§13)

| Outcome | Required | Result |
|---|---|---|
| Idle dev server | auto-fix (low-risk, reversible) | ✅ `auto_fix` |
| Public storage exposure | never blind auto-fix | ✅ `human_escalation_required` |
| Critical production vulnerability | AI never auto-patches prod | ✅ `human_escalation_required` |

---

## 5. Example pipeline output

Idle dev server scenario, abbreviated (full schema = ARCHITECTURE §9.2 / §9.3):

**Structured Issue Object (Module 1 output):**
- `issue_type`: idle_or_overprovisioned_workload · `severity`: medium · `confidence_score`: 0.94
- `ml_result`: Isolation Forest, `is_anomaly`: true
- `xai_explanation` top factor: *"Low CPU usage (3.2%) contributed to an idle/over-provisioned pattern"*
- **§6.6 merge:** carbon + cost signals folded in as contributing evidence, not separate issues
- `llm_user_explanation`: *"BIM Processing Engine was flagged for idle or overprovisioned workload because cpu_usage_percent = 3.2 … It may affect cloud cost, energy use, and carbon emissions."*

**Structured Recommendation Object (Module 2 output):**
- `recommendation_type`: shutdown_schedule_and_resize · `risk_level`: low · `required_execution_mode`: auto_fix
- `optimization_impact_forecast`: cost RM ~2,365 → ~1,182/mo · carbon reduction ~344 kgCO₂e/30d
- `rollback_note`: workload can be restarted; resource limits restorable

---

## 6. Key engineering decisions

| Decision | Rationale | Spec |
|---|---|---|
| Isolation Forest (unsupervised) for detection | Telemetry is unlabelled; learns "normal" without labels | §8.2 |
| Model **frozen** during demo | Same input → same score; reproducible live demo | §8.14 |
| Rules classify issue type, not the model | Deterministic, auditable, credible automation | §5.5.2 |
| Thresholds = baseline × multiplier | Data-derived baselines + domain-set sensitivity; scale-aware | §6.11 |
| LLM explains, never decides | All detection/severity/recommendation/safety is deterministic | §3.2 |
| §6.6 root-cause merge | One action per root cause; cost/energy/carbon are shared evidence | §6.6 |
| Fallbacks everywhere | Rule-only detection + deterministic forecast if a model is missing | §5.9, §8.13 |
| Currency = RM | Consistent demo currency | §B.3 |

---

## 7. Issues encountered & resolved

| Issue | Cause | Resolution |
|---|---|---|
| Python processes hung (stacking background shells) | scikit-learn and xgboost ship **separate OpenMP runtimes**; loading both in one process deadlocks on Windows | Added an OpenMP guard in `ml/common/__init__.py` (`KMP_DUPLICATE_LIB_OK=TRUE`, `OMP_NUM_THREADS=1`) that runs **before** any ML import. `python -m ml.train_all` now runs both model families cleanly in one process. |
| `mock-data-generator` not importable as a package | Directory name contains a hyphen | Generator/controller loaded by path via `importlib`; clean import surfaces exposed at repo root (`ai_pipeline.py`, `mock_api.py`) |
| Device crash mid-run (~8 shells) | Environment crash | Cleared orphaned processes, re-ran and re-verified the full pipeline (exit 0) |

---

## 8. Handoff to the Software Engineering subteam

**Integration is two imports:**

```python
from ai_pipeline import run_detection, run_recommendation, run_pipeline, run_forecast
from mock_api import router as mock_router   # app.include_router(mock_router)
```

**Owned by SE, not us (flagged explicitly):**
- Module 3 (Guardrailed Self-Healing) safety engine + simulated connectors (§7, §13).
  We emit the rule-recommended `required_execution_mode`; the authoritative safety
  decision is the SE backend's.
- The actual LLM API call. We provide the prompt payload **and** a deterministic
  fallback string in every object, so it works with or without a live LLM.

**Before every demo:** re-run `python tests/validate_scenarios.py`. Thresholds are
data-derived (§6.11), so regenerating the historical data can shift which scenarios
fire — the gate catches this.

---

## 9. How to reproduce these results

```bash
pip install -r requirements.txt
python mock-data-generator/generate_historical.py   # synthetic data + baselines
python -m ml.train_all                               # train + freeze all models
python tests/validate_scenarios.py                   # -> RESULT: ALL CHECKS PASSED
```

Full report regenerated at `tests/validation_report.txt` on each run.

---

*Report generated by the AI / Mock Data subteam. See [`../AI_MOCKDATA_README.md`](../AI_MOCKDATA_README.md)
for the integration guide and [`AI_MOCKDATA_PLAN.md`](AI_MOCKDATA_PLAN.md) for the original plan.*

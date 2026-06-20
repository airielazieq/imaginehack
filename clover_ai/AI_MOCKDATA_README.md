# CloudGuard GreenOps — AI / Mock Data Subteam

This is the deliverable from the **AI / Mock Data subteam** for the SE team to integrate.
It covers synthetic telemetry, the live mock controller, the ML detection +
forecast models, SHAP-style explainability, and LLM explanation payloads.

Everything here honors the data contracts in [`ARCHITECTURE.md`](ARCHITECTURE.md)
§9 (Telemetry → Issue → Recommendation). Section references below (e.g. §9.2)
point into that file. Plan: [`docs/AI_MOCKDATA_PLAN.md`](docs/AI_MOCKDATA_PLAN.md).

---

## TL;DR for the SE team

Backend stack: **Python / FastAPI** — ML runs in-process, no separate service.

```python
# 1) Detection + recommendation (Modules 1 & 2 AI parts)
from ai_pipeline import run_detection, run_recommendation, run_pipeline, run_forecast

issues = run_detection(telemetry_dict)        # -> list[Structured Issue Object]  (§9.2)
rec    = run_recommendation(issues[0])        # -> Structured Recommendation Object (§9.3)
result = run_pipeline(telemetry_dict)         # -> {"issues": [...], "recommendations": [...]}

# 2) Mount the mock-data controller endpoints (§11.9)
from mock_api import router as mock_router
app.include_router(mock_router)               # GET/POST /api/mock/*
```

Two top-level integration files are all you need to import: **`ai_pipeline.py`**
and **`mock_api.py`**. Everything else is internal.

---

## First-time setup

```bash
pip install -r requirements.txt

# Generate synthetic history, then train + freeze all models:
python mock-data-generator/generate_historical.py
python -m ml.train_all

# Verify the whole pipeline against the demo scenarios (run before every demo):
python tests/validate_scenarios.py
```

> **Windows note:** scikit-learn and xgboost ship separate OpenMP runtimes;
> loading both in one process can deadlock. `ml/common/__init__.py` sets
> `KMP_DUPLICATE_LIB_OK=TRUE` and `OMP_NUM_THREADS=1` before any ML import to
> prevent this. Keep `ml.common` first in the import chain.

> **Running scripts:** set `PYTHONPATH` to the repo root (or run with `-m`) so
> the `ml` package resolves, e.g. `PYTHONPATH=. python tests/validate_scenarios.py`.

---

## What's in the box

| Path | What |
|---|---|
| `mock-data-generator/data/sample_workloads.json` | 8-workload registry (§10.3) |
| `mock-data-generator/data/healthy_telemetry_baseline.json` | Healthy snapshot per workload (§10.4) |
| `mock-data-generator/data/scenario_payloads.json` | 6 demo scenario patches (§10.5) |
| `mock-data-generator/data/historical_telemetry_training_data.csv` | 960 rows; trains IF + XGBoost (§8.9, §10.9) |
| `mock-data-generator/data/metric_baselines.json` | Per-workload threshold baselines (§6.11) |
| `mock-data-generator/generate_historical.py` | Regenerates the CSV + baselines |
| `mock-data-generator/streams/generator.py` | Telemetry generation (baseline/scenario/stream) |
| `mock-data-generator/controllers/controller.py` | Stateful controller (trigger/reset/stream) |
| `mock_api.py` | FastAPI router for §11.9 + standalone runner |
| `rules/detection_rules.json` | Issue-classification rules + threshold multipliers (§5.5.2, §6.11) |
| `rules/recommendation_rules.json` | NBA rules, merge policy, optimization factors (§6.5, §6.6, §8.11) |
| `ml/isolation_forest/` | Train + freeze + inference (§5.5.1, §8.14) |
| `ml/xgboost_forecast/` | 3 regressors + optimization impact (§8.7–8.12) |
| `ml/explainability/shap_explainer.py` | SHAP-style top factors (§5.6.1, §8.5) |
| `ml/detection/` | Rule classifier + issue builder (§5.5.2, §9.2) |
| `ml/nba/recommender.py` | Recommendation builder (§6, §9.3) |
| `ml/llm/payloads.py` | LLM payloads + deterministic fallbacks (§5.6.2, §5.9) |
| `ml/common/` | Paths, feature defs/encoders, data loaders, OpenMP guard |
| `ml/train_all.py` | Train everything in one command |
| `tests/validate_scenarios.py` | End-to-end demo-readiness gate |

---

## Design guarantees (validated)

`tests/validate_scenarios.py` confirms, deterministically:

- All 6 demo scenarios produce the **correct** `issue_type`, `issue_category`,
  `severity`, and `required_execution_mode`.
- All 8 **healthy** baselines produce **no** issue (the frozen Isolation Forest
  does not false-flag normal workloads).
- The three non-negotiable safety outcomes (§13):
  - Idle dev server → `auto_fix`
  - Public storage exposure → `human_escalation_required`
  - Critical production vulnerability → `human_escalation_required`

The LLM **explains, it never decides** (§3.2). Detection, classification,
severity, recommendation, risk, and execution mode are all deterministic
(ML output + rule engines). The model is **frozen during the demo** (§8.14):
the same telemetry always yields the same anomaly score.

---

## Handoff notes & open items for the SE team

- **Module 3 (Guardrailed Self-Healing) safety engine is yours.** We emit the
  rule-recommended `required_execution_mode` in the recommendation object; the
  authoritative safety decision + simulated connectors (§7, §13) live in the
  SE backend.
- **The LLM call is a handoff point.** `ml/llm/payloads.py` builds the prompt
  payload and always includes a deterministic fallback string
  (`llm_user_explanation`, `llm_recommendation_explanation`). Wire your provider
  to the payload, or ship the fallback as-is.
- **Currency is RM** across all forecast/savings numbers (§B.3).
- **Re-validate before the demo.** Thresholds are data-derived (baseline ×
  multiplier, §6.11). If you regenerate the historical data or change baselines,
  re-run `tests/validate_scenarios.py` — a shifted baseline can change which
  scenarios fire.

See [`mock-data-generator/README.md`](mock-data-generator/README.md) for trigger
behavior and [`ml/README.md`](ml/README.md) for model internals.

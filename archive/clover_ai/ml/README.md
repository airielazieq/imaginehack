# ML, Explainability & Forecasting

Implements ARCHITECTURE.md §5 (Detection), §6 (NBA forecast), §8 (ML stack).

## Module layout

```
common/                 # shared: paths, feature defs/encoders, data loaders, OpenMP guard
  features.py           #   ISO_FOREST_FEATURES (§8.4), XGB_FEATURES (§8.8), fixed encoders
isolation_forest/
  train.py              # fit + freeze IsolationForest + StandardScaler (§5.5.1, §8.14)
  detector.py           # score(telemetry) -> {anomaly_score, is_anomaly}; rule-only fallback (§5.9)
explainability/
  shap_explainer.py     # explain(telemetry) -> SHAP-style top factors (§5.6.1, §8.5)
detection/
  classifier.py         # rule-based issue classification + severity (§5.5.2, §5.8)
  issue_builder.py      # assemble Structured Issue Object + §6.6 root-cause merge (§9.2)
nba/
  recommender.py        # Structured Recommendation Object + risk + execution mode (§6, §9.3)
xgboost_forecast/
  train.py              # 3 regressors: cost / energy / carbon 30d (§8.7)
  forecaster.py         # forecast() + optimization_impact(); deterministic fallback (§8.13)
llm/
  payloads.py           # LLM prompt payloads + deterministic fallback templates (§5.6.2, §5.9)
train_all.py            # train everything in one command
artifacts/              # saved model files (.joblib)
```

## Pipeline (§8.3)

```
telemetry
  -> feature preprocessing + encoding         (common/features.py)
  -> Isolation Forest anomaly score           (isolation_forest/detector.py)
  -> rule-based issue classification           (detection/classifier.py)
  -> root-cause merge (§6.6)                   (detection/issue_builder.py)
  -> SHAP-style top contributing factors       (explainability/shap_explainer.py)
  -> Structured Issue Object (§9.2)            (detection/issue_builder.py)
  -> NBA rule match + risk + execution mode    (nba/recommender.py)
  -> XGBoost 30d forecast + optimization impact (xgboost_forecast/forecaster.py)
  -> LLM explanation (payload + fallback)      (llm/payloads.py)
  -> Structured Recommendation Object (§9.3)
```

## Key decisions

- **Isolation Forest, not a classifier (§8.2):** telemetry is unlabelled.
  IF learns "normal" and flags outliers; *what kind* of issue it is comes from
  the rules in `detection/classifier.py`.
- **Frozen during demo (§8.14):** trained once on the healthy historical set;
  no live retraining, so the same input always yields the same score.
- **SHAP-style contribution:** the primary explainer ranks features by
  standardized deviation from the frozen scaler's learned normal — deterministic,
  fast, and demo-safe. Framed as contribution, never causal proof.
- **Thresholds = baseline × multiplier (§6.11):** baselines are data-derived
  (`metric_baselines.json`), multipliers are domain-set (`rules/detection_rules.json`).
- **Fallbacks everywhere (§5.9, §8.13):** if a model artifact is missing,
  detection drops to rule-only (`fallback_rules_only`) and forecasting drops to a
  deterministic 24h×30 formula (`deterministic_forecast_fallback`) — same output
  schema either way.

## Training

```bash
python mock-data-generator/generate_historical.py   # if the CSV doesn't exist
python -m ml.train_all
```

Artifacts written to `ml/artifacts/`: `isolation_forest.joblib`,
`feature_meta.joblib` (features + scaler), `xgb_{cost,energy,carbon}_30d.joblib`.

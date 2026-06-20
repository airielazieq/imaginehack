"""AI pipeline integration surface for the SE backend.

A single import point that hides the internal ml.* module layout. The SE backend
calls these from its detection / recommendation / forecast routes (§11.3, §11.5,
§11.6). Everything here is deterministic except the (optional) LLM call, which the
SE backend owns — we return ready-to-use payloads and a deterministic fallback
explanation in every object.

    from ai_pipeline import run_detection, run_recommendation, run_pipeline, run_forecast

    issues = run_detection(telemetry_dict)          # -> list[Structured Issue Object]  (§9.2)
    rec    = run_recommendation(issues[0])          # -> Structured Recommendation Object (§9.3)
    result = run_pipeline(telemetry_dict)           # -> {"issues": [...], "recommendations": [...]}
    fc     = run_forecast(telemetry_dict)           # -> forecast_model_result (§8.12)
"""
from __future__ import annotations

from ml.detection import issue_builder
from ml.nba import recommender
from ml.xgboost_forecast import forecaster


def run_detection(telemetry: dict, start_seq: int = 1) -> list[dict]:
    """Module 1: telemetry -> 0+ Structured Issue Objects (§9.2)."""
    return issue_builder.detect(telemetry, start_seq=start_seq)


def run_recommendation(issue: dict, seq: int = 1) -> dict | None:
    """Module 2: issue -> Structured Recommendation Object (§9.3)."""
    return recommender.recommend(issue, seq=seq)


def run_forecast(telemetry: dict) -> dict:
    """XGBoost baseline 30-day forecast (§8.12 forecast_model_result)."""
    return forecaster.forecast(telemetry)


def run_pipeline(telemetry: dict) -> dict:
    """Convenience: detect then recommend for every detected issue."""
    issues = run_detection(telemetry)
    recommendations = []
    for i, issue in enumerate(issues, start=1):
        rec = run_recommendation(issue, seq=i)
        if rec:
            recommendations.append(rec)
    return {"issues": issues, "recommendations": recommendations}


__all__ = ["run_detection", "run_recommendation", "run_forecast", "run_pipeline"]

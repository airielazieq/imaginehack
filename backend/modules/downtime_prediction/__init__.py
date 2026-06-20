"""Downtime Prediction engine (cross-cutting, Requirement 14).

Forecasts *future* workload failure from historical metric trends (a forward
failure forecast, distinct from the Isolation Forest anomaly detector that
flags *current* anomalies). Produces a :class:`~backend.schemas.prediction.
DowntimePrediction` with failure probability, estimated time-to-failure,
contributing signals, confidence, and a 12-point hourly risk timeline.

Public surface:
- :func:`predictor.predict` - pure, side-effect-free trend analysis.
- :func:`predictor.maybe_trigger_preemptive` - best-effort NBA hand-off when
  probability exceeds 70% (Requirement 14.3).
- :func:`timeline.build_risk_timeline` - 12-point hourly risk progression.
"""

from __future__ import annotations

from backend.modules.downtime_prediction import predictor, timeline

__all__ = ["predictor", "timeline"]

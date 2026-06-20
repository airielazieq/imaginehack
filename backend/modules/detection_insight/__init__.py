"""Module 1: Detection & Insight.

Subcomponents:
  - rule_classifier: rule-based issue classification from telemetry + workload
  - severity_assigner: severity + confidence assignment for matched rules

The Isolation Forest, SHAP explainer, LLM explainer, and the orchestrating
detector are added by later tasks (3.2-3.5). These two modules are kept focused
and independently importable so the detector (3.5) can compose them with the ML
and explanation stages.
"""

from backend.modules.detection_insight.rule_classifier import (  # noqa: F401
    RuleMatch,
    classify,
    evaluate_rules,
)
from backend.modules.detection_insight.severity_assigner import (  # noqa: F401
    SeverityAssessment,
    assign_severity,
)

__all__ = [
    "RuleMatch",
    "classify",
    "evaluate_rules",
    "SeverityAssessment",
    "assign_severity",
]

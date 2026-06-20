"""Module 2: Next Best Action.

Subcomponents:
  - nba_engine: rule-based recommendation engine that maps an :class:`Issue`
    to exactly one :class:`Recommendation` using ``recommendation_rules.json``.
  - risk_assessor: deterministic risk level + execution mode selection.

The XGBoost 30-day forecaster (task 4.2) and the Optimization Impact calculator
(task 4.3) are added later and are composed with the rule-based draft produced
here. The event-bus / API wiring lives in task 4.4. These modules are kept
focused and independently importable so the later tasks can compose them.

The LLM only ever explains a recommendation; it never selects the action, risk
level, or execution mode. Rules are authoritative.

Re-exports of in-progress sibling modules (``risk_assessor`` task 4.1,
``nba_engine`` task 4.1) are tolerant: until those modules land, importing this
package (e.g. for the XGBoost forecaster in task 4.2 or the optimization-impact
calculator in task 4.3) must still succeed. Each re-export is therefore guarded
and only added to ``__all__`` once its module is importable.
"""

__all__: list[str] = []

try:  # task 4.1 - risk assessor
    from backend.modules.next_best_action.risk_assessor import (  # noqa: F401
        RiskAssessment,
        assess_risk,
        select_execution_mode,
    )

    __all__ += ["RiskAssessment", "assess_risk", "select_execution_mode"]
except ImportError:  # pragma: no cover - module not yet implemented
    pass

try:  # task 4.1 - rule-based recommendation engine
    from backend.modules.next_best_action.nba_engine import (  # noqa: F401
        NBAEngine,
        RecommendationDraft,
        RecommendationRuleMatch,
        assemble_recommendation,
        build_draft,
        match_rule,
        recommend,
    )

    __all__ += [
        "NBAEngine",
        "RecommendationDraft",
        "RecommendationRuleMatch",
        "assemble_recommendation",
        "build_draft",
        "match_rule",
        "recommend",
    ]
except ImportError:  # pragma: no cover - module not yet implemented
    pass

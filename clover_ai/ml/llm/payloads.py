"""LLM explanation payload builders + deterministic fallback templates.

The AI/Mock-Data subteam owns the *payload shape* and the *fallback templates*
(ARCHITECTURE.md §5.6.2, §5.7, §5.9, §6.10, §8.13). The actual LLM call is a
handoff point: the SE backend may call its provider with build_issue_payload()
output, or use render_issue_explanation_fallback() directly when no LLM is
available. Either way the contract (a short, non-hallucinated, plain-language
string) is preserved.

Per ARCHITECTURE.md §3.2: the LLM explains, it never decides. Nothing here
influences detection, severity, recommendation, or safety — those are
deterministic upstream.
"""
from __future__ import annotations

CURRENCY = "RM"  # §B.3 demo currency


# ---------------------------------------------------------------------------
# Payload builders (what the SE backend would send to the LLM)
# ---------------------------------------------------------------------------
def build_issue_payload(issue: dict) -> dict:
    """Structured prompt payload for an issue explanation (§5.6.2)."""
    factors = issue.get("xai_explanation", {}).get("top_contributing_factors", [])
    top = []
    for fc in factors:
        val = fc.get("value")
        top.append(f"{fc.get('feature')}: {val} ({fc.get('impact')})")
    return {
        "task": "explain_issue",
        "workload_name": issue.get("workload_name"),
        "environment": issue.get("environment"),
        "issue_type": issue.get("issue_type"),
        "issue_category": issue.get("issue_category"),
        "severity": issue.get("severity"),
        "workflow_criticality": issue.get("workflow_criticality"),
        "top_factors": top,
        "constraints": [
            "Be short and clear.",
            "Explain what is wrong and why it matters.",
            "Mention the affected workload and top evidence.",
            "Do not invent technical details.",
            "Do not recommend a final action (Module 2 owns that).",
        ],
    }


def build_recommendation_payload(issue: dict, recommendation: dict) -> dict:
    """Structured prompt payload for a recommendation explanation (§6.10)."""
    forecast = recommendation.get("optimization_impact_forecast", {})
    savings = forecast.get("projected_savings", {})
    return {
        "task": "explain_recommendation",
        "workload_name": recommendation.get("workload_name"),
        "environment": issue.get("environment"),
        "recommended_action": recommendation.get("recommended_action"),
        "recommendation_type": recommendation.get("recommendation_type"),
        "risk_level": recommendation.get("risk_level"),
        "required_execution_mode": recommendation.get("required_execution_mode"),
        "approval_required": recommendation.get("approval_required"),
        "projected_savings": savings,
        "rollback_note": recommendation.get("rollback_note"),
        "constraints": [
            "Explain what action is recommended and why.",
            "State the expected impact using the provided savings numbers.",
            "State whether approval is required.",
            "Mention the rollback note.",
            "Be concise and non-technical.",
        ],
    }


# ---------------------------------------------------------------------------
# Deterministic fallbacks (used when the LLM is unavailable — §5.9, §8.13)
# ---------------------------------------------------------------------------
_ISSUE_IMPACT_AREA = {
    "idle_or_overprovisioned_workload": "cloud cost, energy use, and carbon emissions",
    "carbon_heavy_workload": "energy consumption and carbon emissions",
    "cost_spike_or_waste": "cloud cost",
    "public_storage": "data security and compliance",
    "critical_exposed_vulnerability": "security and the integrity of field operations",
    "no_monitoring": "operational visibility and incident response",
    "high_error_rate": "service reliability",
}


def render_issue_explanation_fallback(issue: dict) -> str:
    """Template explanation per §5.9."""
    name = issue.get("workload_name", "This workload")
    itype = issue.get("issue_type", "an issue")
    area = _ISSUE_IMPACT_AREA.get(itype, "cloud operations")
    factors = issue.get("xai_explanation", {}).get("top_contributing_factors", [])
    evidence = "; ".join(
        f"{fc.get('feature')} = {fc.get('value')}" for fc in factors[:3]
    ) or "abnormal telemetry"
    return (
        f"{name} was flagged for {itype.replace('_', ' ')} because {evidence}. "
        f"It may affect {area}."
    )


def render_recommendation_explanation_fallback(recommendation: dict) -> str:
    """Template recommendation explanation per §5.9 / §8.13."""
    action = recommendation.get("recommended_action", "the recommended action")
    savings = recommendation.get("optimization_impact_forecast", {}).get(
        "projected_savings", {})
    mode = recommendation.get("required_execution_mode", "")
    approval = ("It will be applied automatically." if mode == "auto_fix"
                else "It requires approval before being applied."
                if mode == "user_approval_required"
                else "It is escalated to the responsible human team.")
    cost = savings.get("cost_30d")
    carbon = savings.get("carbon_30d_kgco2e")
    impact = ""
    if cost:
        impact = f" Projected savings: {CURRENCY} {cost:.0f}/month"
        if carbon:
            impact += f" and {carbon:.1f} kgCO2e over 30 days"
        impact += "."
    return f"Recommended action: {action} {approval}{impact}".strip()


__all__ = [
    "build_issue_payload",
    "build_recommendation_payload",
    "render_issue_explanation_fallback",
    "render_recommendation_explanation_fallback",
    "CURRENCY",
]

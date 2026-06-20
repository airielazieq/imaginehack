"""LLM / template explanation generator for Module 1 (Detection & Insight).

Task 3.4 — produce a short (2-3 sentence) plain-language explanation of a detected
issue. The explanation answers *what was flagged*, *why* (top evidence), and *what it
may affect*. It is presentation only.

Design constraints (Requirements 4.1, 4.3, 4.4 / SDD §8-9):

* The LLM is used **only for wording**. It NEVER classifies an issue, assigns
  severity, or recommends an action. Those decisions are made upstream by the rule
  classifier / severity assigner and are simply passed in as already-decided inputs.
* A **deterministic template fallback** is always available with no external API:
  ``"This workload was flagged for {issue_type} because {top_evidence}. It may
  affect {impact_area}."``
* The template is the **default** path and the path exercised by tests — fully
  offline and deterministic. An optional real LLM may be plugged in later via the
  ``llm_fn`` parameter or the ``CLOVER_USE_LLM`` environment flag; when no LLM is
  configured (the default), the template is always used. If a configured LLM call
  fails, we silently fall back to the template so an explanation is always produced.
"""

from __future__ import annotations

import os
from typing import Callable, Sequence, Union

__all__ = [
    "generate_explanation",
    "render_template",
    "humanize_issue_type",
    "format_evidence",
]

# An evidence item may be:
#   * a plain string, e.g. "CPU usage is unusually low"
#   * a 2-tuple (feature, value)
#   * a 3-tuple (feature, value, impact)  -- matches XAIFactor (feature, value, impact)
EvidenceItem = Union[str, Sequence]
Evidence = Union[str, Sequence[EvidenceItem]]

# Optional callable signature for a pluggable LLM. It receives the structured prompt
# context and returns the finished wording. It must NOT influence classification.
LLMFn = Callable[[dict], str]

_MAX_EVIDENCE = 3

# Friendly labels for known issue_category / impact areas. Anything not listed falls
# back to a generic underscore-to-space humanization.
_IMPACT_AREA_LABELS = {
    "security": "security",
    "cost": "cost",
    "energy": "energy consumption",
    "carbon": "carbon emissions",
    "performance": "performance and reliability",
    "monitoring": "observability and monitoring coverage",
    "cost_energy_carbon": "cost, energy, and carbon",
}


def humanize_issue_type(issue_type: str) -> str:
    """Convert a snake_case issue_type into a readable phrase.

    e.g. ``"idle_or_overprovisioned_workload"`` -> ``"idle or overprovisioned
    workload"``. Empty / falsy input yields a safe generic label.
    """
    if not issue_type:
        return "an anomaly"
    return str(issue_type).replace("_", " ").strip().lower()


def humanize_impact_area(impact_area: str) -> str:
    """Convert an impact area / category into a readable phrase."""
    if not impact_area:
        return "this workload"
    key = str(impact_area).strip().lower()
    if key in _IMPACT_AREA_LABELS:
        return _IMPACT_AREA_LABELS[key]
    return key.replace("_", " ")


def _humanize_feature(feature: str) -> str:
    """Make a raw feature name readable (snake_case -> words)."""
    return str(feature).replace("_", " ").strip().lower()


def _evidence_item_to_phrase(item: EvidenceItem) -> str:
    """Render a single evidence item into a clause."""
    if isinstance(item, str):
        return item.strip()
    # Sequence-like (tuple/list). Tolerate 1, 2, or 3+ elements.
    try:
        parts = list(item)
    except TypeError:
        return str(item).strip()

    if len(parts) >= 3:
        feature, value, impact = parts[0], parts[1], parts[2]
        impact_str = str(impact).strip() if impact is not None else ""
        if impact_str:
            return impact_str
        return f"{_humanize_feature(feature)} is {value}"
    if len(parts) == 2:
        feature, value = parts[0], parts[1]
        return f"{_humanize_feature(feature)} is {value}"
    if len(parts) == 1:
        return str(parts[0]).strip()
    return ""


def format_evidence(top_evidence: Evidence) -> str:
    """Join the top evidence items into a single human-readable phrase.

    Accepts either a pre-formatted string or a sequence of evidence items
    (strings, ``(feature, value)`` pairs, or ``(feature, value, impact)`` triples,
    matching ``XAIFactor``). Only the first :data:`_MAX_EVIDENCE` items are used so
    the explanation stays short.
    """
    if top_evidence is None:
        return "unusual telemetry was observed"

    if isinstance(top_evidence, str):
        phrase = top_evidence.strip()
        return phrase or "unusual telemetry was observed"

    phrases = []
    for item in list(top_evidence)[:_MAX_EVIDENCE]:
        phrase = _evidence_item_to_phrase(item)
        if phrase:
            phrases.append(phrase)

    if not phrases:
        return "unusual telemetry was observed"
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return f"{', '.join(phrases[:-1])}, and {phrases[-1]}"


def render_template(
    issue_type: str,
    top_evidence: Evidence,
    impact_area: str,
) -> str:
    """Deterministic, offline template explanation (always available).

    Produces exactly two sentences of the form::

        "This workload was flagged for {issue_type} because {top_evidence}. It may
        affect {impact_area}."

    The output is purely a function of its inputs (deterministic) and is wording
    only — it does not alter classification, severity, or recommendations.
    """
    issue_phrase = humanize_issue_type(issue_type)
    evidence_phrase = format_evidence(top_evidence)
    impact_phrase = humanize_impact_area(impact_area)
    return (
        f"This workload was flagged for {issue_phrase} because {evidence_phrase}. "
        f"It may affect {impact_phrase}."
    )


def _llm_enabled(use_llm: bool | None) -> bool:
    """Resolve whether a real LLM should be attempted.

    Defaults to OFF. Explicit ``use_llm`` wins; otherwise the ``CLOVER_USE_LLM``
    env flag is consulted ("1"/"true"/"yes"/"on" enable it).
    """
    if use_llm is not None:
        return use_llm
    flag = os.environ.get("CLOVER_USE_LLM", "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def generate_explanation(
    issue_type: str,
    top_evidence: Evidence,
    impact_area: str,
    *,
    llm_fn: LLMFn | None = None,
    use_llm: bool | None = None,
) -> str:
    """Generate a 2-3 sentence plain-language explanation for a detected issue.

    Parameters
    ----------
    issue_type:
        The already-classified issue type (e.g. ``"public_storage"``). Used for
        wording only.
    top_evidence:
        Top contributing evidence/factors from SHAP/rules. Either a pre-formatted
        string or a sequence of strings / ``(feature, value)`` / ``(feature, value,
        impact)`` items.
    impact_area:
        The affected area / issue category (e.g. ``"security"`` or
        ``"cost_energy_carbon"``).
    llm_fn:
        Optional pluggable LLM callable used purely for rewording. It receives a
        structured context dict and returns the finished text. If it raises or
        returns empty/invalid output, the deterministic template is used instead.
    use_llm:
        Force-enable/disable the LLM path. Defaults to ``None`` which consults the
        ``CLOVER_USE_LLM`` env flag (off by default).

    Returns
    -------
    str
        A non-empty explanation string. The template fallback is the default and is
        always available offline; the explanation never changes the issue's
        classification or severity.
    """
    template_text = render_template(issue_type, top_evidence, impact_area)

    if llm_fn is not None and _llm_enabled(use_llm):
        try:
            context = {
                "issue_type": issue_type,
                "top_evidence": format_evidence(top_evidence),
                "impact_area": impact_area,
                "template": template_text,
            }
            llm_text = llm_fn(context)
            if isinstance(llm_text, str) and llm_text.strip():
                return llm_text.strip()
        except Exception:
            # LLM is wording-only and best-effort. Any failure -> deterministic
            # template so an explanation is always produced.
            pass

    return template_text

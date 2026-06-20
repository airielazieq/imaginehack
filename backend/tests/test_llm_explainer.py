"""Tests for the LLM / template explanation generator (task 3.4).

Covers Requirements 4.1, 4.3, 4.4:

* 4.1 — an Issue gets a plain-language user-facing explanation.
* 4.3 — when the LLM is unavailable, a pre-defined template is used.
* 4.4 — the LLM is used exclusively for wording, never for classification/severity.

The default and tested path is the deterministic, fully-offline template fallback.
Both example-based unit tests and a property-based test are included.
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.modules.detection_insight.llm_explainer import (
    format_evidence,
    generate_explanation,
    humanize_impact_area,
    humanize_issue_type,
    render_template,
)

# The 7 defined issue types from detection_rules.json.
ISSUE_TYPES = [
    "public_storage",
    "critical_exposed_vulnerability",
    "idle_or_overprovisioned_workload",
    "carbon_heavy_workload",
    "no_monitoring",
    "high_error_rate",
    "cost_spike_or_waste",
]

IMPACT_AREAS = [
    "security",
    "cost",
    "energy",
    "carbon",
    "performance",
    "monitoring",
    "cost_energy_carbon",
]


def _count_sentences(text: str) -> int:
    """Count sentences as non-empty segments terminated by a period."""
    return len([s for s in re.split(r"(?<=\.)\s+", text.strip()) if s.strip()])


# ---------------------------------------------------------------------------
# Example-based unit tests
# ---------------------------------------------------------------------------
def test_template_is_non_empty_and_two_to_three_sentences():
    """Explanation is non-empty and contains 2-3 sentences."""
    text = generate_explanation(
        "public_storage",
        [("public_storage", True, "storage bucket is publicly accessible")],
        "security",
    )
    assert isinstance(text, str)
    assert text.strip()
    assert 2 <= _count_sentences(text) <= 3


def test_mentions_humanized_issue_type_and_impact_area():
    """The wording surfaces the humanized issue type and impact area."""
    text = generate_explanation(
        "idle_or_overprovisioned_workload",
        ["CPU usage is unusually low for the runtime"],
        "cost_energy_carbon",
    )
    assert "idle or overprovisioned workload" in text
    # cost_energy_carbon humanizes to "cost, energy, and carbon"
    assert humanize_impact_area("cost_energy_carbon") in text
    assert "idle_or_overprovisioned_workload" not in text  # raw form not leaked


def test_matches_spec_template_shape():
    """Output matches the SDD template shape exactly for known inputs."""
    text = render_template(
        "no_monitoring",
        "monitoring is disabled",
        "monitoring",
    )
    assert text == (
        "This workload was flagged for no monitoring because monitoring is "
        "disabled. It may affect observability and monitoring coverage."
    )


def test_deterministic_same_inputs_same_output():
    """Template fallback is deterministic: identical inputs -> identical output."""
    args = (
        "high_error_rate",
        [("error_rate_percent", 12.5, "error rate is well above threshold")],
        "performance",
    )
    first = generate_explanation(*args)
    second = generate_explanation(*args)
    assert first == second


def test_evidence_formats_string_pair_and_triple():
    """Evidence accepts strings, (feature, value) pairs, and XAIFactor triples."""
    assert format_evidence("already a phrase") == "already a phrase"
    assert format_evidence([("cpu_usage_percent", 4.0)]) == "cpu usage percent is 4.0"
    # triple uses the impact string when present
    assert (
        format_evidence([("cpu_usage_percent", 4.0, "CPU is idle")]) == "CPU is idle"
    )


def test_evidence_joined_nicely():
    """Multiple evidence items are joined with commas and a trailing 'and'."""
    phrase = format_evidence(["a", "b", "c"])
    assert phrase == "a, b, and c"
    two = format_evidence(["a", "b"])
    assert two == "a and b"


def test_empty_evidence_still_produces_explanation():
    """Missing evidence still yields a complete, non-empty explanation."""
    text = generate_explanation("cost_spike_or_waste", [], "cost")
    assert text.strip()
    assert 2 <= _count_sentences(text) <= 3


# ---------------------------------------------------------------------------
# Requirement 4.4 — LLM is wording-only; never alters classification/severity
# ---------------------------------------------------------------------------
def test_default_path_is_offline_template_even_with_llm_provided():
    """With no use_llm flag, an attached LLM is NOT invoked (template is default)."""
    calls = []

    def fake_llm(context):
        calls.append(context)
        return "SHOULD NOT BE USED"

    text = generate_explanation(
        "public_storage", ["public bucket"], "security", llm_fn=fake_llm
    )
    assert calls == []  # LLM not called by default
    assert text == render_template("public_storage", ["public bucket"], "security")


def test_llm_used_only_for_wording_when_enabled():
    """When explicitly enabled, the LLM only rewrites wording; inputs are unchanged."""
    received = {}

    def fake_llm(context):
        received.update(context)
        return "Reworded but same meaning explanation."

    text = generate_explanation(
        "public_storage",
        ["public bucket"],
        "security",
        llm_fn=fake_llm,
        use_llm=True,
    )
    assert text == "Reworded but same meaning explanation."
    # The LLM receives already-decided classification context; it does not produce it.
    assert received["issue_type"] == "public_storage"
    assert received["impact_area"] == "security"


def test_llm_failure_falls_back_to_template():
    """If the LLM call raises, the deterministic template is returned."""

    def broken_llm(context):
        raise RuntimeError("LLM endpoint down")

    text = generate_explanation(
        "high_error_rate",
        ["error rate is high"],
        "performance",
        llm_fn=broken_llm,
        use_llm=True,
    )
    assert text == render_template(
        "high_error_rate", ["error rate is high"], "performance"
    )


def test_module_does_not_decide_classification_or_severity():
    """The public API has no severity/classification parameter or return value.

    generate_explanation only returns a wording string; it cannot change the
    issue_type or severity that were decided upstream.
    """
    import inspect

    sig = inspect.signature(generate_explanation)
    params = set(sig.parameters)
    assert "severity" not in params
    assert "confidence_score" not in params
    # issue_type is an INPUT (already decided), and the return is just text.
    result = generate_explanation("no_monitoring", ["monitoring off"], "monitoring")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Property-based test (template determinism + content invariants)
# ---------------------------------------------------------------------------
@settings(max_examples=200, deadline=None)
@given(
    issue_type=st.sampled_from(ISSUE_TYPES),
    impact_area=st.sampled_from(IMPACT_AREAS),
    evidence=st.lists(
        st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=1,
            max_size=12,
        ),
        min_size=0,
        max_size=5,
    ),
)
def test_property_explanation_invariants(issue_type, impact_area, evidence):
    """For any defined issue type/impact area and evidence list:

    * output is a non-empty string,
    * it is 2-3 sentences,
    * it mentions the humanized issue type and impact area,
    * it is deterministic (template path, default/offline).
    """
    text = generate_explanation(issue_type, evidence, impact_area)
    again = generate_explanation(issue_type, evidence, impact_area)

    assert isinstance(text, str) and text.strip()
    assert text == again  # deterministic
    assert 2 <= _count_sentences(text) <= 3
    assert humanize_issue_type(issue_type) in text
    assert humanize_impact_area(impact_area) in text

"""End-to-end validation of the AI/Mock-Data pipeline against the demo scenarios.

For each scenario (ARCHITECTURE.md §10.5) this runs the full
detect -> recommend pipeline on the patched telemetry and asserts the
deterministic outcome matches the `expected` block in scenario_payloads.json
(issue_type, issue_category, severity, execution_mode). Also confirms every
HEALTHY baseline produces NO issue (frozen Isolation Forest must not false-flag).

This is the §6.11 / plan-§5 re-validation gate. Run before every demo:

    python -m tests.validate_scenarios

Writes a UTF-8 copy of the report to tests/validation_report.txt.
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")

from ml.common import data, paths  # noqa: E402
from ml.detection import issue_builder  # noqa: E402
from ml.nba import recommender  # noqa: E402

_LINES: list[str] = []


def out(*args) -> None:
    line = " ".join(str(a) for a in args)
    _LINES.append(line)
    print(line, flush=True)


def _full_telemetry(workload_id: str, scenario_id: str | None) -> dict:
    base = data.get_baseline(workload_id)
    if scenario_id:
        base.update(data.get_scenario(scenario_id)["patch"])
    return base


def _check(label: str, got, want) -> tuple[bool, str]:
    mark = "OK " if got == want else "FAIL"
    return got == want, f"      [{mark}] {label}: got={got!r} want={want!r}"


def main() -> int:
    failures = 0
    out("=" * 72)
    out("SCENARIO VALIDATION (detect -> recommend)")
    out("=" * 72)

    for sc in data.load_scenarios():
        wid, exp = sc["target_workload"], sc["expected"]
        t = _full_telemetry(wid, sc["scenario_id"])
        issues = issue_builder.detect(t)
        out(f"\n{sc['scenario_id']}  (target {wid})")
        if not issues:
            out("      [FAIL] no issue detected")
            failures += 1
            continue
        issue = issues[0]
        rec = recommender.recommend(issue)
        for ok, line in [
            _check("issue_type", issue["issue_type"], exp["issue_type"]),
            _check("issue_category", issue["issue_category"], exp["issue_category"]),
            _check("severity", issue["severity"], exp["severity"]),
            _check("execution_mode", rec["required_execution_mode"], exp["execution_mode"]),
        ]:
            out(line)
            failures += 0 if ok else 1
        save = rec["optimization_impact_forecast"]["projected_savings"]
        out(f"      anomaly={issue['ml_result']['is_anomaly']} "
            f"conf={issue['confidence_score']} risk={rec['risk_level']} "
            f"savings(cost/carbon)={save['cost_30d']}/{save['carbon_30d_kgco2e']}")

    out("\n" + "=" * 72)
    out("HEALTHY BASELINES (must produce NO issue)")
    out("=" * 72)
    for wid in data.load_baselines():
        issues = issue_builder.detect(_full_telemetry(wid, None))
        if issues:
            out(f"  [FAIL] {wid} flagged: {[i['issue_type'] for i in issues]}")
            failures += 1
        else:
            out(f"  [OK ] {wid} healthy")

    out("\n" + "=" * 72)
    out(f"RESULT: {failures} check(s) FAILED" if failures else "RESULT: ALL CHECKS PASSED")
    out("=" * 72)

    report = paths.REPO_ROOT / "tests" / "validation_report.txt"
    report.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

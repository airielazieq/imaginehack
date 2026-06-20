"""Approval queue management for Module 3 (Guardrailed Self-Healing).

A global, in-memory queue of remediations awaiting user approval. Items
represent :class:`Recommendation` objects whose
``required_execution_mode == "user_approval_required"`` (or escalations that
have been routed here for review).

Behaviour (Requirements 9.1 - 9.4, spec 06 section 7):

- **Severity ordering** -- the queue is always read back sorted
  ``Critical -> High -> Medium -> Low`` (ties broken oldest-first) so the most
  urgent items surface at the top (Req 9.1).
- **Escalation countdown** -- high/critical-risk items carry a 15-minute
  escalation deadline (``approval_escalation_timeout_minutes`` from
  ``safety_rules.json``). When the deadline passes without user action the item
  auto-escalates to ``escalated`` (Req 9.2, 9.3).
- **Decisions** -- ``approve`` / ``deny`` move an item to a terminal state;
  ``snooze`` pushes the escalation deadline out by the configured default
  (30 minutes) and keeps the item live (Req 9.4 / spec 06 section 7).

Time handling is fully injectable: every method that cares about "now" accepts
an optional ``now`` argument so escalation-on-timeout can be tested by passing a
future timestamp rather than sleeping.

The module exposes a process-wide singleton :data:`approval_queue` that the
safety router (task 5.3) populates and the approvals API (``api/approvals.py``)
reads from.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from backend.core.config import load_policy
from backend.schemas.recommendation import Recommendation

logger = logging.getLogger("clover.self_healing.approval_queue")

Severity = Literal["low", "medium", "high", "critical"]
ApprovalStatus = Literal["pending", "snoozed", "approved", "denied", "escalated"]

# Severity ordering (Critical highest). Used to sort the queue and to derive a
# fallback severity from a recommendation's risk_level.
_SEVERITY_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Risk levels that get a live escalation countdown while pending. Critical items
# normally route straight to human escalation, but if one lands here it should
# still carry (and respect) a countdown.
_ESCALATION_RISK_LEVELS: frozenset[str] = frozenset({"high", "critical"})

# Statuses that are still "live" in the queue (shown to operators).
ACTIVE_STATUSES: frozenset[str] = frozenset({"pending", "snoozed", "escalated"})

# Defaults; overridden from safety_rules.json at construction time.
_DEFAULT_ESCALATION_MINUTES = 15
_DEFAULT_SNOOZE_MINUTES = 30


def severity_rank(severity: str) -> int:
    """Return the ordinal rank of a severity (low=0 .. critical=3)."""
    return _SEVERITY_ORDER.get(severity, 0)


def _now(now: datetime | None) -> datetime:
    """Resolve an injectable ``now`` to an aware UTC datetime."""
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


class InvalidTransition(Exception):
    """Raised when an approval item cannot move to the requested state."""


@dataclass
class ApprovalItem:
    """A single remediation awaiting approval in the global queue."""

    approval_id: str
    recommendation_id: str
    issue_id: str
    workload_id: str
    severity: Severity
    risk_level: str
    recommended_action: str
    action_category: str
    mcp_tools: list[str] = field(default_factory=list)
    environment: str | None = None
    ai_rationale: str = ""
    status: ApprovalStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    escalation_deadline: datetime | None = None
    snoozed_until: datetime | None = None
    resolved_at: datetime | None = None
    selected_mcp_tools: list[str] = field(default_factory=list)

    def seconds_until_escalation(self, now: datetime | None = None) -> int | None:
        """Remaining seconds on the escalation countdown (None if no timer)."""
        if self.escalation_deadline is None:
            return None
        delta = (self.escalation_deadline - _now(now)).total_seconds()
        return max(0, int(delta))

    def to_dict(self, now: datetime | None = None) -> dict:
        """JSON-serialisable view including a live countdown for the UI."""
        return {
            "approval_id": self.approval_id,
            "recommendation_id": self.recommendation_id,
            "issue_id": self.issue_id,
            "workload_id": self.workload_id,
            "severity": self.severity,
            "risk_level": self.risk_level,
            "recommended_action": self.recommended_action,
            "action_category": self.action_category,
            "mcp_tools": list(self.mcp_tools),
            "environment": self.environment,
            "ai_rationale": self.ai_rationale,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "escalation_deadline": (
                self.escalation_deadline.isoformat()
                if self.escalation_deadline
                else None
            ),
            "snoozed_until": (
                self.snoozed_until.isoformat() if self.snoozed_until else None
            ),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "seconds_until_escalation": self.seconds_until_escalation(now),
            "selected_mcp_tools": list(self.selected_mcp_tools),
        }


class ApprovalQueue:
    """Thread-safe in-memory approval queue with escalation timers."""

    def __init__(
        self,
        *,
        escalation_timeout_minutes: int | None = None,
        snooze_default_minutes: int | None = None,
    ) -> None:
        timers = self._load_timers()
        self.escalation_timeout_minutes = (
            escalation_timeout_minutes
            if escalation_timeout_minutes is not None
            else timers.get(
                "approval_escalation_timeout_minutes", _DEFAULT_ESCALATION_MINUTES
            )
        )
        self.snooze_default_minutes = (
            snooze_default_minutes
            if snooze_default_minutes is not None
            else timers.get("snooze_default_minutes", _DEFAULT_SNOOZE_MINUTES)
        )
        self._items: dict[str, ApprovalItem] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _load_timers() -> dict:
        """Load escalation / snooze timers from the safety policy (best-effort)."""
        try:
            return load_policy("safety_rules").get("timers", {})
        except Exception:  # noqa: BLE001 - fall back to module defaults
            logger.warning("Could not load safety_rules timers; using defaults")
            return {}

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #
    def add(
        self,
        recommendation: Recommendation,
        *,
        severity: str | None = None,
        environment: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalItem:
        """Add a recommendation to the queue (idempotent on recommendation id).

        ``severity`` drives queue ordering; when omitted it is looked up from the
        originating issue (falling back to the recommendation's risk level).
        High/critical-risk items receive a 15-minute escalation countdown.
        """
        resolved_severity = severity or self._resolve_severity(recommendation)
        reference = _now(now)

        deadline: datetime | None = None
        if recommendation.risk_level in _ESCALATION_RISK_LEVELS:
            deadline = reference + timedelta(minutes=self.escalation_timeout_minutes)

        item = ApprovalItem(
            approval_id=recommendation.recommendation_id,
            recommendation_id=recommendation.recommendation_id,
            issue_id=recommendation.issue_id,
            workload_id=recommendation.workload_id,
            severity=resolved_severity,  # type: ignore[arg-type]
            risk_level=recommendation.risk_level,
            recommended_action=recommendation.recommended_action,
            action_category=recommendation.action_category,
            mcp_tools=list(recommendation.mcp_tools),
            environment=environment,
            ai_rationale=recommendation.llm_recommendation_explanation,
            status="pending",
            created_at=reference,
            escalation_deadline=deadline,
        )
        with self._lock:
            self._items[item.approval_id] = item
        logger.info(
            "Queued approval %s (severity=%s, risk=%s) for workload %s",
            item.approval_id,
            item.severity,
            item.risk_level,
            item.workload_id,
        )
        return item

    def _resolve_severity(self, recommendation: Recommendation) -> str:
        """Best-effort severity lookup from the originating issue."""
        try:
            from backend.services import issue_service

            issue = issue_service.get_issue(recommendation.issue_id)
            if issue and issue.get("severity"):
                return issue["severity"]
        except Exception:  # noqa: BLE001 - severity is non-critical for routing
            logger.debug("Issue severity lookup failed; using risk_level fallback")
        return recommendation.risk_level

    def approve(
        self,
        approval_id: str,
        *,
        selected_mcp_tools: list[str] | None = None,
        now: datetime | None = None,
    ) -> ApprovalItem | None:
        """Approve a pending/snoozed item. Returns ``None`` if not found."""
        return self._decide(
            approval_id, "approved", now=now, selected_mcp_tools=selected_mcp_tools
        )

    def deny(self, approval_id: str, *, now: datetime | None = None) -> ApprovalItem | None:
        """Deny a pending/snoozed item. Returns ``None`` if not found."""
        return self._decide(approval_id, "denied", now=now)

    def _decide(
        self,
        approval_id: str,
        new_status: ApprovalStatus,
        *,
        now: datetime | None,
        selected_mcp_tools: list[str] | None = None,
    ) -> ApprovalItem | None:
        reference = _now(now)
        with self._lock:
            self._process_escalations(reference)
            item = self._items.get(approval_id)
            if item is None:
                return None
            if item.status not in ("pending", "snoozed"):
                raise InvalidTransition(
                    f"Approval '{approval_id}' is '{item.status}' and can no "
                    f"longer be {new_status}."
                )
            item.status = new_status
            item.resolved_at = reference
            if selected_mcp_tools is not None:
                item.selected_mcp_tools = list(selected_mcp_tools)
        logger.info("Approval %s -> %s", approval_id, new_status)
        return item

    def snooze(
        self,
        approval_id: str,
        *,
        minutes: int | None = None,
        now: datetime | None = None,
    ) -> ApprovalItem | None:
        """Push the escalation countdown out and keep the item live.

        Defaults to ``snooze_default_minutes`` (30). Returns ``None`` if the item
        does not exist; raises :class:`InvalidTransition` if it is terminal.
        """
        reference = _now(now)
        snooze_minutes = minutes if minutes is not None else self.snooze_default_minutes
        with self._lock:
            self._process_escalations(reference)
            item = self._items.get(approval_id)
            if item is None:
                return None
            if item.status not in ("pending", "snoozed", "escalated"):
                raise InvalidTransition(
                    f"Approval '{approval_id}' is '{item.status}' and cannot be "
                    "snoozed."
                )
            new_deadline = reference + timedelta(minutes=snooze_minutes)
            item.escalation_deadline = new_deadline
            item.snoozed_until = new_deadline
            item.status = "snoozed"
        logger.info("Approval %s snoozed for %d min", approval_id, snooze_minutes)
        return item

    # ------------------------------------------------------------------ #
    # Escalation
    # ------------------------------------------------------------------ #
    def _process_escalations(self, now: datetime) -> list[ApprovalItem]:
        """Auto-escalate any live item whose escalation deadline has passed.

        Caller must hold ``self._lock``.
        """
        escalated: list[ApprovalItem] = []
        for item in self._items.values():
            if (
                item.status in ("pending", "snoozed")
                and item.escalation_deadline is not None
                and now >= item.escalation_deadline
            ):
                item.status = "escalated"
                item.resolved_at = now
                escalated.append(item)
                logger.info(
                    "Approval %s auto-escalated (deadline %s reached)",
                    item.approval_id,
                    item.escalation_deadline.isoformat(),
                )
        return escalated

    def process_escalations(self, *, now: datetime | None = None) -> list[ApprovalItem]:
        """Public hook to run escalation timers; returns newly escalated items."""
        reference = _now(now)
        with self._lock:
            return list(self._process_escalations(reference))

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, approval_id: str) -> ApprovalItem | None:
        """Return a single item by id, or ``None``."""
        with self._lock:
            return self._items.get(approval_id)

    def list_items(
        self,
        *,
        now: datetime | None = None,
        include_resolved: bool = False,
    ) -> list[ApprovalItem]:
        """Return queue items sorted Critical -> High -> Medium -> Low.

        Escalation timers are processed first so the returned view reflects any
        timeouts. By default only live items (pending/snoozed/escalated) are
        returned; ``include_resolved=True`` adds approved/denied items.
        """
        reference = _now(now)
        with self._lock:
            self._process_escalations(reference)
            items = list(self._items.values())
        if not include_resolved:
            items = [i for i in items if i.status in ACTIVE_STATUSES]
        items.sort(key=lambda i: (-severity_rank(i.severity), i.created_at))
        return items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        """Drop all items (used in tests and on demo reset)."""
        with self._lock:
            self._items.clear()


# Process-wide singleton used by the API and the safety router.
approval_queue = ApprovalQueue()

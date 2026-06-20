"""Service layer: data-access and business logic for platform entities.

Services encapsulate SQLite read/write access so API routers stay thin and
the same logic can be reused across modules (detection, scoring, dashboard).
"""

from backend.services import audit_service

__all__ = ["audit_service"]

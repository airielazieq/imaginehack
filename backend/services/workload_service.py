"""Workload persistence service (CRUD).

Encapsulates read/write access to the ``workloads`` table. The frequently
queried/displayed fields are promoted to dedicated columns; the full
:class:`Workload` document is also stored as JSON in the ``data`` column so the
canonical representation survives schema evolution.
"""

from __future__ import annotations

import json
import logging

from backend.core.database import connection
from backend.schemas.workload import Workload

logger = logging.getLogger("clover.services.workload")

# Columns promoted out of the JSON document into dedicated table columns.
_PROMOTED_COLUMNS = (
    "workload_id",
    "workload_name",
    "workload_type",
    "cloud_service_type",
    "environment",
    "region",
    "owner_team",
    "construction_workflow",
    "workflow_criticality",
    "status",
)


def _row_to_workload_dict(row) -> dict:
    """Reconstruct a workload dict from a DB row.

    Prefers the full JSON ``data`` document when present, falling back to the
    promoted columns for rows inserted without a JSON payload (e.g. test seeds).
    """
    data = row["data"]
    if data:
        return json.loads(data)
    return {col: row[col] for col in _PROMOTED_COLUMNS}


def upsert_workload(workload: Workload, *, db_path: str | None = None) -> str:
    """Insert or update a workload, returning its id.

    Existing rows (matched by ``workload_id``) are updated in place and their
    ``updated_at`` timestamp refreshed; new rows are inserted.
    """
    payload = workload.model_dump(mode="json")
    data_json = json.dumps(payload)
    with connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO workloads (
                workload_id, workload_name, workload_type, cloud_service_type,
                environment, region, owner_team, construction_workflow,
                workflow_criticality, status, data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workload_id) DO UPDATE SET
                workload_name         = excluded.workload_name,
                workload_type         = excluded.workload_type,
                cloud_service_type    = excluded.cloud_service_type,
                environment           = excluded.environment,
                region                = excluded.region,
                owner_team            = excluded.owner_team,
                construction_workflow = excluded.construction_workflow,
                workflow_criticality  = excluded.workflow_criticality,
                status                = excluded.status,
                data                  = excluded.data,
                updated_at            = datetime('now')
            """,
            (
                workload.workload_id,
                workload.workload_name,
                workload.workload_type,
                workload.cloud_service_type,
                workload.environment,
                workload.region,
                workload.owner_team,
                workload.construction_workflow,
                workload.workflow_criticality,
                workload.status,
                data_json,
            ),
        )
    logger.info("Upserted workload %s", workload.workload_id)
    return workload.workload_id


def get_workload(workload_id: str, *, db_path: str | None = None) -> dict | None:
    """Return a single workload as a dict, or ``None`` if it does not exist."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM workloads WHERE workload_id = ?",
            (workload_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_workload_dict(row)


def list_workloads(*, db_path: str | None = None) -> list[dict]:
    """Return all workloads as a list of dicts, ordered by id."""
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM workloads ORDER BY workload_id"
        ).fetchall()
    return [_row_to_workload_dict(row) for row in rows]


def workload_exists(workload_id: str, *, db_path: str | None = None) -> bool:
    """Return ``True`` if a workload with the given id exists."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM workloads WHERE workload_id = ?",
            (workload_id,),
        ).fetchone()
    return row is not None

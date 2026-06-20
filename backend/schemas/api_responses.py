"""Standard API response envelope wrappers.

All API responses use one of two consistent envelopes:

    success: {"success": true,  "data": {...}, "message": "..."}
    error:   {"error": true,    "code": "VALIDATION_ERROR", "message": "...",
              "details": {...}}
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Envelope for a successful API response."""

    success: bool = True
    data: T | None = None
    message: str | None = None


class ErrorResponse(BaseModel):
    """Envelope for a failed API response.

    Serializes to ``{"error": true, "code": <string>, "message": <string>}``
    with an optional ``details`` object.
    """

    error: bool = True
    code: str
    message: str
    details: dict | None = None


def success(data: object = None, message: str | None = None) -> dict:
    """Build a success envelope dict."""
    return {"success": True, "data": data, "message": message}


def error(code: str, message: str, details: dict | None = None) -> dict:
    """Build an error envelope dict.

    Always shaped as ``{"error": true, "code": ..., "message": ...}``.
    """
    payload: dict = {"error": True, "code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return payload

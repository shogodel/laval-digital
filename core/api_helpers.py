"""Standardized JSON response helpers for consistent API envelope."""
from flask import jsonify, g
from typing import Any


def api_response(
    success: bool = True,
    data: Any | None = None,
    error: str | None = None,
    message: str | None = None,
    status_code: int = 200,
) -> tuple:
    """Return a standardized JSON API response.

    Envelope: {"success": bool, "data": ..., "error": ..., "message": ..., "request_id": "..."}
    """
    body: dict[str, Any] = {
        "success": success,
        "request_id": getattr(g, "request_id", ""),
    }
    if data is not None:
        body["data"] = data
        if isinstance(data, dict):
            for k, v in data.items():
                if k not in body:
                    body[k] = v
    if error is not None:
        body["error"] = error
    if message is not None:
        body["message"] = message
    return jsonify(body), status_code


def api_success(data: Any = None, message: str | None = None, status_code: int = 200) -> tuple:
    """Return a success response."""
    return api_response(success=True, data=data, message=message, status_code=status_code)


def api_error(error: str, status_code: int = 400, data: Any = None) -> tuple:
    """Return an error response."""
    return api_response(success=False, error=error, data=data, status_code=status_code)

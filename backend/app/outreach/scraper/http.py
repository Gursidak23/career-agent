"""Shared sync HTTP helper for job-board API calls.

Job sources are called from synchronous FastAPI route handlers (run in the
threadpool), so a blocking httpx.Client keeps the code simple.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 CareerAgent/1.0"
    ),
    "Accept": "application/json, text/plain, */*",
}


def get_json(url: str, *, params: dict[str, Any] | None = None, timeout: float = 25.0) -> Any:
    """GET a URL and parse JSON, raising RuntimeError on any failure."""
    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS, follow_redirects=True) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        log.warning("job source request failed: %s", exc)
        raise RuntimeError(f"Request to {url} failed: {exc}") from exc
    except ValueError as exc:  # JSON decode error
        raise RuntimeError(f"Invalid JSON from {url}: {exc}") from exc


def post_json(
    url: str,
    *,
    json_body: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> Any:
    """POST JSON and parse the JSON response, raising RuntimeError on failure."""
    try:
        with httpx.Client(timeout=timeout, headers=DEFAULT_HEADERS, follow_redirects=True) as client:
            resp = client.post(url, params=params, json=json_body)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        log.warning("job source POST failed: %s", exc)
        raise RuntimeError(f"Request to {url} failed: {exc}") from exc
    except ValueError as exc:  # JSON decode error
        raise RuntimeError(f"Invalid JSON from {url}: {exc}") from exc

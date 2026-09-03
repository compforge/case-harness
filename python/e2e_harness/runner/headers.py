"""Shared request-header construction.

Used by both ``JSONRunner`` and ``SSERunner`` (and any future runner) to
inject auth headers, merge per-request extras, and apply explicit drops —
the last part lets negative-auth tests intentionally omit a required header.
"""

from __future__ import annotations

from e2e_harness.core.config import E2EConfig


def build_auth_headers(
    config: E2EConfig,
    *,
    extra: dict[str, str] | None = None,
    exclude: set[str] | None = None,
    content_type: str = "application/json",
) -> dict[str, str]:
    """Build a header dict: Content-Type + Service headers + extras − exclude.

    Resolution order:
      1. ``Content-Type`` (overridable via ``extra``)
      2. Generic headers from ``config.service.headers``
      3. Per-request ``extra`` (overrides everything above)
      4. Drop keys in ``exclude`` (after merging, so callers can omit auth headers
         injected by the runner — needed for missing-auth negative tests)
    """
    headers: dict[str, str] = {"Content-Type": content_type}
    headers.update(config.service.headers)
    if extra:
        headers.update(extra)
    if exclude:
        for h in exclude:
            headers.pop(h, None)
    return headers

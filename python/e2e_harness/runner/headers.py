"""Shared request-header construction.

Used by both ``JSONRunner`` and ``SSERunner`` (and any future runner) to
inject auth headers, merge per-request extras, and apply explicit drops —
the last part lets negative-auth tests intentionally omit a required header.
"""

from __future__ import annotations

from e2e_harness.core.env import Env


def build_auth_headers(
    env: Env,
    *,
    extra: dict[str, str] | None = None,
    exclude: set[str] | None = None,
    content_type: str = "application/json",
) -> dict[str, str]:
    """Build a header dict: Content-Type + env.auth → header map + extras − exclude.

    Resolution order:
      1. ``Content-Type`` (overridable via ``extra``)
      2. Generic headers from ``env.auth.headers``
      3. Per-request ``extra`` (overrides everything above)
      4. Drop keys in ``exclude`` (after merging, so callers can omit auth headers
         injected by the runner — needed for missing-auth negative tests)
    """
    headers: dict[str, str] = {"Content-Type": content_type}
    headers.update(env.auth.headers)
    if extra:
        headers.update(extra)
    if exclude:
        for h in exclude:
            headers.pop(h, None)
    return headers

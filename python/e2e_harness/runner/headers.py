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
      2. Auth tenant_id / user_id mapped through ``env.auth.headers``
      3. Any ``env.auth.extra`` headers
      4. Per-request ``extra`` (overrides everything above)
      5. Drop keys in ``exclude`` (after merging, so callers can omit auth headers
         injected by the runner — needed for missing-auth negative tests)
    """
    headers: dict[str, str] = {"Content-Type": content_type}
    auth = env.auth
    header_map = auth.headers
    if "tenant_id" in header_map and auth.tenant_id:
        headers[header_map["tenant_id"]] = auth.tenant_id
    if "user_id" in header_map and auth.user_id:
        headers[header_map["user_id"]] = auth.user_id
    for k, v in auth.extra.items():
        headers[k] = v
    if extra:
        headers.update(extra)
    if exclude:
        for h in exclude:
            headers.pop(h, None)
    return headers

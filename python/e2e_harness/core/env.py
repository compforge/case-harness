"""Environment configuration loader.

Reads config.yaml with ${VAR:-default} interpolation, falling back to
environment variables when config.yaml is absent.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServiceConfig:
    name: str = ""
    base_url: str = ""


@dataclass
class AuthConfig:
    tenant_id: str = ""
    user_id: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class RuntimeConfig:
    http_timeout_s: int = 120
    poll_interval_ms: int = 500
    poll_timeout_s: int = 60
    parallel: int = 4


@dataclass
class Capabilities:
    known: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverConfigSection:
    """Optional dev-time tooling config for discover/scaffold."""

    source_root: str = ""  # dir to scan for @case/@spec (relative to config.yaml dir)
    test_root: str = ""  # where tests land, grouped <test_root>/<group>/ (relative to config.yaml dir)


@dataclass
class Env:
    service: ServiceConfig = field(default_factory=ServiceConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    profile: str = "full"
    capabilities: Capabilities = field(default_factory=Capabilities)
    custom: dict[str, str] = field(default_factory=dict)
    discover: DiscoverConfigSection = field(default_factory=DiscoverConfigSection)


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _interpolate(value: str) -> str:
    """Replace ${VAR} and ${VAR:-default} patterns with environment values."""

    def _replace(m: re.Match) -> str:
        expr = m.group(1)
        if ":-" in expr:
            var, default = expr.split(":-", 1)
            return os.environ.get(var, default)
        val = os.environ.get(expr)
        if val is None:
            raise ValueError(
                f"environment variable ${{{expr}}} is required but not set"
            )
        return val

    return _ENV_PATTERN.sub(_replace, value)


def _interpolate_recursive(obj: Any) -> Any:
    if isinstance(obj, str):
        return _interpolate(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(v) for v in obj]
    return obj


def load_env(config_path: str | Path = "config.yaml") -> Env:
    """Load Env from config.yaml (with env interpolation) or pure env vars."""
    path = Path(config_path)

    if path.exists():
        raw = yaml.safe_load(path.read_text())
        if raw is None:
            raw = {}
        data = _interpolate_recursive(raw)
    else:
        data = _build_from_env()

    return _parse_env(data)


def _build_from_env() -> dict:
    """Fallback: construct config dict purely from environment variables."""
    return {
        "service": {
            "name": os.environ.get("E2E_SERVICE_NAME", ""),
            "base_url": os.environ.get("E2E_BASE_URL", ""),
        },
        "auth": {
            "tenant_id": os.environ.get("E2E_TENANT_ID", ""),
            "user_id": os.environ.get("E2E_USER_ID", ""),
        },
        "runtime": {},
        "profile": os.environ.get("E2E_PROFILE", "full"),
        "custom": {},
    }


def _parse_env(data: dict) -> Env:
    svc = data.get("service", {})
    auth_raw = data.get("auth", {})
    rt = data.get("runtime", {})
    custom = data.get("custom", {})
    disc = data.get("discover", {}) or {}

    auth_headers = auth_raw.get("headers") or {}
    auth_extra = {
        k: v
        for k, v in auth_raw.items()
        if k not in ("tenant_id", "user_id", "headers")
    }

    return Env(
        service=ServiceConfig(
            name=svc.get("name", ""),
            base_url=svc.get("base_url", "").rstrip("/"),
        ),
        auth=AuthConfig(
            tenant_id=auth_raw.get("tenant_id", ""),
            user_id=auth_raw.get("user_id", ""),
            headers={str(k): str(v) for k, v in auth_headers.items()}
            if auth_headers
            else {},
            extra=auth_extra,
        ),
        runtime=RuntimeConfig(
            http_timeout_s=int(rt.get("http_timeout_s", 120)),
            poll_interval_ms=int(rt.get("poll_interval_ms", 500)),
            poll_timeout_s=int(rt.get("poll_timeout_s", 60)),
            parallel=int(rt.get("parallel", 4)),
        ),
        profile=data.get("profile", "full"),
        custom={str(k): str(v) for k, v in custom.items()} if custom else {},
        discover=DiscoverConfigSection(
            source_root=str(disc.get("source_root", "")),
            test_root=str(disc.get("test_root", "")),
        ),
    )

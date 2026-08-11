"""Unit tests for e2e_harness core components."""

from textwrap import dedent

import pytest

from e2e_harness.core.env import Env, load_env, _interpolate
from e2e_harness.core.profile import require_profile, require_capability
from e2e_harness.runner.base import Outcome


class TestInterpolation:
    def test_simple_var(self, monkeypatch):
        monkeypatch.setenv("FOO", "bar")
        assert _interpolate("${FOO}") == "bar"

    def test_var_with_default(self, monkeypatch):
        monkeypatch.delenv("MISSING", raising=False)
        assert _interpolate("${MISSING:-fallback}") == "fallback"

    def test_var_with_default_uses_env_if_present(self, monkeypatch):
        monkeypatch.setenv("PRESENT", "actual")
        assert _interpolate("${PRESENT:-fallback}") == "actual"

    def test_missing_required_var_raises(self, monkeypatch):
        monkeypatch.delenv("REQUIRED", raising=False)
        with pytest.raises(ValueError, match="REQUIRED"):
            _interpolate("${REQUIRED}")

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        assert _interpolate("${A} ${B}") == "hello world"


class TestLoadEnv:
    def test_load_from_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_URL", "http://localhost:8080")
        monkeypatch.setenv("MY_TOKEN", "token-1")

        config = tmp_path / "config.yaml"
        config.write_text(
            dedent("""\
            service:
              name: test-svc
              base_url: ${MY_URL}
            auth:
              headers:
                Authorization: Bearer ${MY_TOKEN}
            profile: minimal
            custom:
              ttl: "60"
        """)
        )

        env = load_env(config)
        assert env.service.name == "test-svc"
        assert env.service.base_url == "http://localhost:8080"
        assert env.auth.headers == {"Authorization": "Bearer token-1"}
        assert env.profile == "minimal"
        assert env.custom["ttl"] == "60"

    def test_load_from_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("E2E_BASE_URL", "http://fallback:9090")
        monkeypatch.setenv("E2E_AUTH_HEADERS", '{"Authorization":"Bearer fallback"}')
        monkeypatch.setenv("E2E_PROFILE", "full")

        env = load_env(tmp_path / "nonexistent.yaml")
        assert env.service.base_url == "http://fallback:9090"
        assert env.auth.headers == {"Authorization": "Bearer fallback"}
        assert env.profile == "full"

    def test_load_auth_headers_mapping(self, tmp_path, monkeypatch):
        config = tmp_path / "config.yaml"
        config.write_text(
            dedent("""\
            service:
              base_url: http://localhost:8080
            auth:
              headers:
                X-Top-Tenant-Id: t1
                X-Top-User-Id: u1
        """)
        )

        env = load_env(config)
        assert env.auth.headers == {
            "X-Top-Tenant-Id": "t1",
            "X-Top-User-Id": "u1",
        }


class TestBuildAuthHeaders:
    def _env(self, **auth_kwargs):
        from e2e_harness.core.env import AuthConfig, ServiceConfig

        return Env(
            service=ServiceConfig(base_url="http://localhost"),
            auth=AuthConfig(**auth_kwargs),
        )

    def test_headers_are_injected_directly(self):
        from e2e_harness.runner.headers import build_auth_headers

        env = self._env(
            headers={"X-Top-Tenant-Id": "t1", "X-Top-User-Id": "u1"},
        )
        headers = build_auth_headers(env)
        assert headers["X-Top-Tenant-Id"] == "t1"
        assert headers["X-Top-User-Id"] == "u1"

    def test_no_auth_headers_when_empty(self):
        from e2e_harness.runner.headers import build_auth_headers

        env = self._env()
        headers = build_auth_headers(env)
        assert "X-Top-Tenant-Id" not in headers
        assert headers == {"Content-Type": "application/json"}

    def test_extra_overrides_auth(self):
        from e2e_harness.runner.headers import build_auth_headers

        env = self._env(headers={"X-T": "t1"})
        headers = build_auth_headers(env, extra={"X-T": "override"})
        assert headers["X-T"] == "override"

    def test_exclude_drops_after_merge(self):
        from e2e_harness.runner.headers import build_auth_headers

        env = self._env(
            headers={"X-T": "t1", "X-U": "u1"},
        )
        headers = build_auth_headers(env, exclude={"X-T"})
        assert "X-T" not in headers
        assert headers["X-U"] == "u1"

    def test_custom_content_type(self):
        from e2e_harness.runner.headers import build_auth_headers

        env = self._env()
        headers = build_auth_headers(env, content_type="text/event-stream")
        assert headers["Content-Type"] == "text/event-stream"


class TestOutcome:
    def test_field_access(self):
        o = Outcome(status_code=200, body={"data": {"id": "abc", "items": [1, 2, 3]}})
        assert o.field("data.id") == "abc"
        assert o.field("data.items.0") == 1
        assert o.field("data.items.2") == 3
        assert o.field("data.missing") is None
        assert o.field("nonexistent.path") is None

    def test_field_str(self):
        o = Outcome(status_code=200, body={"name": "hello", "count": 42})
        assert o.field_str("name") == "hello"
        assert o.field_str("count") == "42"
        assert o.field_str("missing") == ""

    def test_serialization_roundtrip(self):
        o = Outcome(
            status_code=201, body={"id": "x"}, duration_ms=150, raw=b"raw bytes"
        )
        d = o.to_dict()
        restored = Outcome.from_dict(d)
        assert restored.status_code == 201
        assert restored.body == {"id": "x"}
        assert restored.duration_ms == 150


class TestProfile:
    def test_require_profile_skip(self):
        env = Env(profile="minimal")
        with pytest.raises(pytest.skip.Exception):
            require_profile(env, "full", "warm_off")

    def test_require_profile_pass(self):
        env = Env(profile="full")
        require_profile(env, "full", "minimal")  # should not raise

    def test_require_capability_unknown(self):
        env = Env()
        with pytest.raises(pytest.skip.Exception):
            require_capability(env, "storage_class")

    def test_require_capability_missing(self):
        from e2e_harness.core.env import Capabilities

        env = Env(capabilities=Capabilities(known=True, data={"other": "val"}))
        with pytest.raises(pytest.skip.Exception):
            require_capability(env, "storage_class")

    def test_require_capability_present(self):
        from e2e_harness.core.env import Capabilities

        env = Env(capabilities=Capabilities(known=True, data={"storage_class": "gp3"}))
        require_capability(env, "storage_class")  # should not raise

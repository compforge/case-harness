package core

import (
	"os"
	"path/filepath"
	"testing"
)

func TestInterpolate(t *testing.T) {
	os.Setenv("TEST_VAR", "hello")
	defer os.Unsetenv("TEST_VAR")

	got, err := interpolate("${TEST_VAR}")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "hello" {
		t.Fatalf("expected %q, got %q", "hello", got)
	}
}

func TestInterpolateDefault(t *testing.T) {
	os.Unsetenv("MISSING_VAR")

	got, err := interpolate("${MISSING_VAR:-fallback}")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "fallback" {
		t.Fatalf("expected %q, got %q", "fallback", got)
	}
}

func TestInterpolateMissingRequired(t *testing.T) {
	os.Unsetenv("REQUIRED_VAR")

	_, err := interpolate("${REQUIRED_VAR}")
	if err == nil {
		t.Fatal("expected error for missing required var")
	}
}

func TestLoadEnvFromYAML(t *testing.T) {
	os.Setenv("MY_URL", "http://localhost:9090")
	os.Setenv("MY_TOKEN", "token-1")
	defer func() {
		os.Unsetenv("MY_URL")
		os.Unsetenv("MY_TOKEN")
	}()

	dir := t.TempDir()
	configPath := filepath.Join(dir, "config.yaml")
	content := `
service:
  name: test-svc
  base_url: ${MY_URL}
auth:
  headers:
    Authorization: Bearer ${MY_TOKEN}
profile: minimal
custom:
  ttl: "60"
`
	if err := os.WriteFile(configPath, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	env, err := LoadEnv(configPath)
	if err != nil {
		t.Fatalf("LoadEnv error: %v", err)
	}
	if env.Service.Name != "test-svc" {
		t.Errorf("service.name = %q, want %q", env.Service.Name, "test-svc")
	}
	if env.Service.BaseURL != "http://localhost:9090" {
		t.Errorf("service.base_url = %q, want %q", env.Service.BaseURL, "http://localhost:9090")
	}
	if env.Auth.Headers["Authorization"] != "Bearer token-1" {
		t.Errorf("auth headers = %#v", env.Auth.Headers)
	}
	if env.Profile != "minimal" {
		t.Errorf("profile = %q, want %q", env.Profile, "minimal")
	}
	if env.Custom["ttl"] != "60" {
		t.Errorf("custom.ttl = %q, want %q", env.Custom["ttl"], "60")
	}
}

func TestLoadEnvFallback(t *testing.T) {
	os.Setenv("E2E_BASE_URL", "http://fallback:8080")
	os.Setenv("E2E_AUTH_HEADERS", `{"Authorization":"Bearer fallback"}`)
	os.Setenv("E2E_PROFILE", "full")
	defer func() {
		os.Unsetenv("E2E_BASE_URL")
		os.Unsetenv("E2E_AUTH_HEADERS")
		os.Unsetenv("E2E_PROFILE")
	}()

	env, err := LoadEnv("/nonexistent/config.yaml")
	if err != nil {
		t.Fatalf("LoadEnv error: %v", err)
	}
	if env.Service.BaseURL != "http://fallback:8080" {
		t.Errorf("base_url = %q, want %q", env.Service.BaseURL, "http://fallback:8080")
	}
	if env.Auth.Headers["Authorization"] != "Bearer fallback" {
		t.Errorf("auth headers = %#v", env.Auth.Headers)
	}
	if env.Profile != "full" {
		t.Errorf("profile = %q, want %q", env.Profile, "full")
	}
}

func TestLoadEnvRejectsInvalidAuthHeadersJSON(t *testing.T) {
	os.Setenv("E2E_AUTH_HEADERS", "not-json")
	defer os.Unsetenv("E2E_AUTH_HEADERS")
	if _, err := LoadEnv("/nonexistent/config.yaml"); err == nil {
		t.Fatal("expected invalid E2E_AUTH_HEADERS error")
	}
}

func TestLoadEnvRejectsNonMappingAuthHeaders(t *testing.T) {
	configPath := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(configPath, []byte("auth:\n  headers: bearer-token\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadEnv(configPath); err == nil {
		t.Fatal("expected non-mapping auth.headers error")
	}
}

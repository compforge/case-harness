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
	os.Setenv("MY_TENANT", "t1")
	os.Setenv("MY_USER", "u1")
	defer func() {
		os.Unsetenv("MY_URL")
		os.Unsetenv("MY_TENANT")
		os.Unsetenv("MY_USER")
	}()

	dir := t.TempDir()
	configPath := filepath.Join(dir, "config.yaml")
	content := `
service:
  name: test-svc
  base_url: ${MY_URL}
auth:
  tenant_id: ${MY_TENANT}
  user_id: ${MY_USER}
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
	if env.Auth.TenantID != "t1" {
		t.Errorf("auth.tenant_id = %q, want %q", env.Auth.TenantID, "t1")
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
	os.Setenv("E2E_TENANT_ID", "fb-tenant")
	os.Setenv("E2E_USER_ID", "fb-user")
	os.Setenv("E2E_PROFILE", "full")
	defer func() {
		os.Unsetenv("E2E_BASE_URL")
		os.Unsetenv("E2E_TENANT_ID")
		os.Unsetenv("E2E_USER_ID")
		os.Unsetenv("E2E_PROFILE")
	}()

	env, err := LoadEnv("/nonexistent/config.yaml")
	if err != nil {
		t.Fatalf("LoadEnv error: %v", err)
	}
	if env.Service.BaseURL != "http://fallback:8080" {
		t.Errorf("base_url = %q, want %q", env.Service.BaseURL, "http://fallback:8080")
	}
	if env.Auth.TenantID != "fb-tenant" {
		t.Errorf("tenant_id = %q, want %q", env.Auth.TenantID, "fb-tenant")
	}
	if env.Profile != "full" {
		t.Errorf("profile = %q, want %q", env.Profile, "full")
	}
}

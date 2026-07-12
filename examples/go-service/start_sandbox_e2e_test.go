//go:build e2e

package sandbox_e2e

import (
	"context"
	"strconv"
	"testing"
	"time"

	"github.com/qiankunli/case-harness/go/e2e/core"
	"github.com/qiankunli/case-harness/go/e2e/judge"
	"github.com/qiankunli/case-harness/go/e2e/runner"
)

func TestStartSandbox_HappyPath(t *testing.T) {
	env, err := core.LoadEnv("config.yaml")
	if err != nil {
		t.Fatalf("load env: %v", err)
	}
	core.RequireProfile(t, env, "full", "minimal")

	r := runner.NewJSONRunner(env)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	conv := core.UniqueID(env.Custom["conv_prefix"])
	ttl, _ := strconv.ParseInt(env.Custom["ttl_seconds"], 10, 64)
	pvcTTL, _ := strconv.ParseInt(env.Custom["pvc_ttl_seconds"], 10, 64)

	outcome := r.Trigger(t, ctx, runner.Request{
		Method: "POST",
		Path:   "/api/v1/sandboxes/start",
		Body: map[string]any{
			"tenant_id":       env.Auth.TenantID,
			"user_id":         env.Auth.UserID,
			"conversation_id": conv,
			"ttl_seconds":     ttl,
			"pvc_ttl_seconds": pvcTTL,
		},
	})

	judge.Assert(t, outcome,
		judge.Status(200),
		judge.FieldNotEmpty("sandbox_name"),
		judge.FieldEq("conversation_id", conv),
		judge.NoError(),
	)

	// cleanup
	core.Cleanup(t, "stop sandbox", func() {
		r.Trigger(t, ctx, runner.Request{
			Method: "POST",
			Path:   "/api/v1/sandboxes/stop",
			Body:   map[string]any{"conversation_id": conv},
		})
	})
}

func TestStartSandbox_Reuse(t *testing.T) {
	env, err := core.LoadEnv("config.yaml")
	if err != nil {
		t.Fatalf("load env: %v", err)
	}

	r := runner.NewJSONRunner(env)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()

	conv := core.UniqueID(env.Custom["conv_prefix"])
	ttl, _ := strconv.ParseInt(env.Custom["ttl_seconds"], 10, 64)

	body := runner.Request{
		Method: "POST",
		Path:   "/api/v1/sandboxes/start",
		Body: map[string]any{
			"tenant_id":       env.Auth.TenantID,
			"user_id":         env.Auth.UserID,
			"conversation_id": conv,
			"ttl_seconds":     ttl,
		},
	}

	first := r.Trigger(t, ctx, body)
	judge.Assert(t, first, judge.Status(200), judge.FieldNotEmpty("sandbox_name"))

	second := r.Trigger(t, ctx, body)
	judge.Assert(t, second, judge.Status(200))

	// same sandbox should be reused
	judge.Assert(t, second,
		judge.FieldEq("sandbox_name", first.FieldStr("sandbox_name")),
	)

	core.Cleanup(t, "stop sandbox", func() {
		r.Trigger(t, ctx, runner.Request{
			Method: "POST",
			Path:   "/api/v1/sandboxes/stop",
			Body:   map[string]any{"conversation_id": conv},
		})
	})
}

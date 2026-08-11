package judge

import (
	"testing"

	"github.com/compforge/case-harness/go/e2e/runner"
)

func TestAssertReturnsMismatch(t *testing.T) {
	outcome := &runner.Outcome{StatusCode: 201, Body: []byte(`{"id":"x"}`)}
	if err := Assert(outcome, Status(200), FieldNotEmpty("id")); err == nil {
		t.Fatal("expected status mismatch")
	}
	if err := Assert(outcome, Status(201), FieldNotEmpty("id")); err != nil {
		t.Fatal(err)
	}
}

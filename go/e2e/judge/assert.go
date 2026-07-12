// Package judge provides assertion helpers for e2e test outcomes.
package judge

import (
	"fmt"
	"regexp"
	"testing"

	"github.com/qiankunli/case-harness/go/e2e/runner"
)

// Assertion is a check function applied to an Outcome.
type Assertion func(t *testing.T, o *runner.Outcome)

// Assert runs all assertions against the outcome. Stops at first failure.
func Assert(t *testing.T, o *runner.Outcome, asserts ...Assertion) {
	t.Helper()
	for _, a := range asserts {
		a(t, o)
	}
}

// Status asserts HTTP status code equals want.
func Status(want int) Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		if o.StatusCode != want {
			t.Fatalf("expected status %d, got %d", want, o.StatusCode)
		}
	}
}

// Status2xx asserts HTTP status code is in 2xx range.
func Status2xx() Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		if o.StatusCode < 200 || o.StatusCode >= 300 {
			t.Fatalf("expected 2xx status, got %d", o.StatusCode)
		}
	}
}

// FieldEq asserts body field at dot-path equals want.
func FieldEq(path string, want any) Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		got := o.Field(path)
		if fmt.Sprint(got) != fmt.Sprint(want) {
			t.Fatalf("field %q: expected %v, got %v", path, want, got)
		}
	}
}

// FieldNotEmpty asserts body field at dot-path is present and non-empty.
func FieldNotEmpty(path string) Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		got := o.Field(path)
		if got == nil || fmt.Sprint(got) == "" {
			t.Fatalf("field %q: expected non-empty value, got %v", path, got)
		}
	}
}

// FieldContains asserts body field string contains substring.
func FieldContains(path string, substr string) Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		got := o.FieldStr(path)
		if got == "" {
			t.Fatalf("field %q: expected to contain %q, got empty", path, substr)
		}
		if !contains(got, substr) {
			t.Fatalf("field %q: expected to contain %q, got %q", path, substr, got)
		}
	}
}

// FieldMatches asserts body field string matches regex pattern.
func FieldMatches(path string, pattern string) Assertion {
	re := regexp.MustCompile(pattern)
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		got := o.FieldStr(path)
		if !re.MatchString(got) {
			t.Fatalf("field %q: expected to match %q, got %q", path, pattern, got)
		}
	}
}

// FieldIn asserts body field value is one of the allowed values.
func FieldIn(path string, values ...any) Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		got := o.Field(path)
		gotStr := fmt.Sprint(got)
		for _, v := range values {
			if gotStr == fmt.Sprint(v) {
				return
			}
		}
		t.Fatalf("field %q: expected one of %v, got %v", path, values, got)
	}
}

// NoError asserts response has no error/code fields.
func NoError() Assertion {
	return func(t *testing.T, o *runner.Outcome) {
		t.Helper()
		m := o.BodyMap()
		if m == nil {
			return
		}
		if errMsg, _ := m["error"].(string); errMsg != "" {
			code, _ := m["code"].(string)
			t.Fatalf("unexpected error: error=%q code=%q", errMsg, code)
		}
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 ||
		findSubstring(s, substr))
}

func findSubstring(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

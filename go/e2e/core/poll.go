package core

import (
	"testing"
	"time"
)

// Retry calls fn until it succeeds (err == nil) or the deadline passes.
//
// fn returns (retryable, err): a non-retryable error fails the test immediately;
// a retryable error is retried after interval. This is the "poll until stable,
// retry only on known-transient" pattern — e.g. a second create that briefly
// returns a volume-detach-pending code — without baking any specific error code
// into the harness; the caller decides what counts as retryable.
func Retry(t *testing.T, interval, timeout time.Duration, fn func() (retryable bool, err error)) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for {
		retryable, err := fn()
		if err == nil {
			return
		}
		if !retryable {
			t.Fatalf("Retry: non-retryable error: %v", err)
		}
		if time.Now().After(deadline) {
			t.Fatalf("Retry: still failing after %s: %v", timeout, err)
		}
		time.Sleep(interval)
	}
}

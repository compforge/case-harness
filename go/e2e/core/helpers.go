package core

import (
	"fmt"
	"os"
	"sync/atomic"
	"testing"
	"time"
)

var seq atomic.Int64

// UniqueID generates a unique identifier for test isolation.
func UniqueID(prefix string) string {
	return fmt.Sprintf("%s%d-%d", prefix, os.Getpid(), seq.Add(1))
}

// Cleanup registers a best-effort cleanup function that logs but never fails.
func Cleanup(t *testing.T, description string, fn func()) {
	t.Helper()
	t.Cleanup(func() {
		defer func() {
			if r := recover(); r != nil {
				t.Logf("cleanup %q panicked (best-effort): %v", description, r)
			}
		}()
		fn()
	})
}

// PollUntil repeatedly calls check until it returns true or timeout expires.
func PollUntil(t *testing.T, interval, timeout time.Duration, check func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for {
		if check() {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("PollUntil timed out after %s", timeout)
		}
		time.Sleep(interval)
	}
}

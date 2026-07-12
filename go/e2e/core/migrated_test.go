package core

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestUniqueIDForEncodesTestNameAndIsUnique(t *testing.T) {
	a := UniqueIDFor("e2e-", "TestFoo/sub case")
	b := UniqueIDFor("e2e-", "TestFoo/sub case")
	if a == b {
		t.Fatal("UniqueIDFor returned duplicate ids")
	}
	if !strings.HasPrefix(a, "e2e-TestFoo-sub-case-") {
		t.Errorf("id = %q, want sanitized test name prefix", a)
	}
}

func TestCapabilitiesAccessors(t *testing.T) {
	unknown := Capabilities{Known: false}
	if unknown.Has("storage_class") || unknown.String("storage_class") != "" {
		t.Error("unknown capabilities must report absent")
	}
	known := Capabilities{Known: true, Data: map[string]any{"storage_class": "gp3", "nil_key": nil}}
	if !known.Has("storage_class") || known.String("storage_class") != "gp3" {
		t.Error("present capability not reported")
	}
	if known.Has("nil_key") {
		t.Error("nil-valued capability should count as absent")
	}
}

func TestFetchCapabilitiesDegradesGracefully(t *testing.T) {
	jsonSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"storage_class":"gp3"}`))
	}))
	defer jsonSrv.Close()
	caps := FetchCapabilities(jsonSrv.URL, "/healthz")
	if !caps.Known || caps.String("storage_class") != "gp3" {
		t.Errorf("JSON healthz not parsed: %+v", caps)
	}

	plainSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	defer plainSrv.Close()
	if FetchCapabilities(plainSrv.URL, "/healthz").Known {
		t.Error("plain-text healthz should leave Known=false, not error out")
	}

	if FetchCapabilities("http://127.0.0.1:0", "/healthz").Known {
		t.Error("unreachable healthz should leave Known=false")
	}
}

func TestRetry(t *testing.T) {
	// retryable until the 3rd attempt, then succeeds.
	n := 0
	Retry(t, time.Millisecond, time.Second, func() (bool, error) {
		n++
		if n < 3 {
			return true, errors.New("transient")
		}
		return false, nil
	})
	if n != 3 {
		t.Errorf("expected 3 attempts, got %d", n)
	}
}

package runner

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/qiankunli/case-harness/go/e2e/core"
)

// JSONRunner sends HTTP requests and parses JSON responses into Outcome.
type JSONRunner struct {
	env    *core.Env
	client *http.Client
}

// NewJSONRunner creates a runner for standard JSON REST/RPC APIs.
func NewJSONRunner(env *core.Env) *JSONRunner {
	return &JSONRunner{
		env: env,
		client: &http.Client{
			Timeout: time.Duration(env.Runtime.HTTPTimeoutS) * time.Second,
		},
	}
}

func (r *JSONRunner) Trigger(t *testing.T, ctx context.Context, req Request) *Outcome {
	t.Helper()

	var bodyReader io.Reader
	if req.Body != nil {
		data, err := json.Marshal(req.Body)
		if err != nil {
			t.Fatalf("marshal request body: %v", err)
		}
		bodyReader = bytes.NewReader(data)
	}

	method := req.Method
	if method == "" {
		method = http.MethodPost
	}

	url := r.env.Service.BaseURL + req.Path
	httpReq, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}

	// Set headers
	httpReq.Header.Set("Content-Type", "application/json")
	if r.env.Auth.TenantID != "" {
		httpReq.Header.Set("X-AS-Tenant-ID", r.env.Auth.TenantID)
	}
	if r.env.Auth.UserID != "" {
		httpReq.Header.Set("X-AS-User-ID", r.env.Auth.UserID)
	}
	for k, v := range r.env.Auth.Extra {
		httpReq.Header.Set(k, v)
	}
	for k, v := range req.Headers {
		httpReq.Header.Set(k, v)
	}

	// Set query params
	if len(req.Query) > 0 {
		q := httpReq.URL.Query()
		for k, v := range req.Query {
			q.Set(k, v)
		}
		httpReq.URL.RawQuery = q.Encode()
	}

	start := time.Now()
	resp, err := r.client.Do(httpReq)
	if err != nil {
		t.Fatalf("HTTP request failed: %v", err)
	}
	defer resp.Body.Close()
	durationMS := time.Since(start).Milliseconds()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read response body: %v", err)
	}

	// Parse response headers
	headers := make(map[string]string, len(resp.Header))
	for k := range resp.Header {
		headers[k] = resp.Header.Get(k)
	}

	// Parse JSON body if content-type is JSON
	var body json.RawMessage
	ct := resp.Header.Get("Content-Type")
	if len(raw) > 0 && (ct == "" || bytes.Contains([]byte(ct), []byte("json"))) {
		if json.Valid(raw) {
			body = raw
		}
	}

	return &Outcome{
		StatusCode: resp.StatusCode,
		Body:       body,
		Headers:    headers,
		DurationMS: durationMS,
		Metadata:   map[string]any{},
		Raw:        raw,
	}
}

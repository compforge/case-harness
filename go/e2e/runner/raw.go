package runner

import (
	"bytes"
	"context"
	"net/http"
)

// RawRequest builds an *http.Request carrying a verbatim body (not marshaled from
// a typed struct) with the env's standard headers applied. Negative tests use it
// to send payloads the typed Request path would never produce — unknown fields,
// malformed JSON, wrong types — to exercise the server's input validation.
func (r *JSONRunner) RawRequest(ctx context.Context, method, path string, body []byte) (*http.Request, error) {
	url := r.env.Service.BaseURL + path
	req, err := http.NewRequestWithContext(ctx, method, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if r.env.Auth.TenantID != "" {
		req.Header.Set("X-AS-Tenant-ID", r.env.Auth.TenantID)
	}
	if r.env.Auth.UserID != "" {
		req.Header.Set("X-AS-User-ID", r.env.Auth.UserID)
	}
	for k, v := range r.env.Auth.Extra {
		req.Header.Set(k, v)
	}
	return req, nil
}

// Client exposes the runner's underlying HTTP client so raw requests built via
// RawRequest are sent with the same timeout and transport as typed ones.
func (r *JSONRunner) Client() *http.Client {
	return r.client
}

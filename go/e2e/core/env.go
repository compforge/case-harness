// Package core provides environment configuration loading for e2e tests.
package core

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

type ServiceConfig struct {
	Name    string `yaml:"name"`
	BaseURL string `yaml:"base_url"`
}

type AuthConfig struct {
	Headers map[string]string `yaml:"headers"`
}

type RuntimeConfig struct {
	HTTPTimeoutS   int `yaml:"http_timeout_s"`
	PollIntervalMS int `yaml:"poll_interval_ms"`
	PollTimeoutS   int `yaml:"poll_timeout_s"`
	Parallel       int `yaml:"parallel"`
}

type Capabilities struct {
	Known bool
	Data  map[string]any
}

type Env struct {
	Service      ServiceConfig
	Auth         AuthConfig
	Runtime      RuntimeConfig
	Profile      string
	Capabilities Capabilities
	Custom       map[string]string
}

var envPattern = regexp.MustCompile(`\$\{([^}]+)\}`)

func interpolate(s string) (string, error) {
	var lastErr error
	result := envPattern.ReplaceAllStringFunc(s, func(match string) string {
		expr := match[2 : len(match)-1] // strip ${ and }
		if idx := strings.Index(expr, ":-"); idx >= 0 {
			varName := expr[:idx]
			defaultVal := expr[idx+2:]
			if val := os.Getenv(varName); val != "" {
				return val
			}
			return defaultVal
		}
		val := os.Getenv(expr)
		if val == "" {
			lastErr = fmt.Errorf("environment variable ${%s} is required but not set", expr)
		}
		return val
	})
	return result, lastErr
}

func interpolateMap(raw map[string]any) (map[string]any, error) {
	out := make(map[string]any, len(raw))
	for k, v := range raw {
		resolved, err := interpolateValue(v)
		if err != nil {
			return nil, err
		}
		out[k] = resolved
	}
	return out, nil
}

func interpolateValue(v any) (any, error) {
	switch val := v.(type) {
	case string:
		return interpolate(val)
	case map[string]any:
		return interpolateMap(val)
	case []any:
		out := make([]any, len(val))
		for i, item := range val {
			resolved, err := interpolateValue(item)
			if err != nil {
				return nil, err
			}
			out[i] = resolved
		}
		return out, nil
	default:
		return v, nil
	}
}

// LoadEnv loads configuration from a YAML file with env var interpolation.
// Falls back to environment variables if the file doesn't exist.
func LoadEnv(configPath string) (*Env, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return loadFromEnvVars()
		}
		return nil, fmt.Errorf("read config %s: %w", configPath, err)
	}

	var raw map[string]any
	if err := yaml.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse config %s: %w", configPath, err)
	}

	resolved, err := interpolateMap(raw)
	if err != nil {
		return nil, err
	}

	return parseEnv(resolved), nil
}

func loadFromEnvVars() (*Env, error) {
	headers, err := authHeadersFromEnv()
	if err != nil {
		return nil, err
	}
	return &Env{
		Service: ServiceConfig{
			Name:    os.Getenv("E2E_SERVICE_NAME"),
			BaseURL: os.Getenv("E2E_BASE_URL"),
		},
		Auth: AuthConfig{Headers: headers},
		Runtime: RuntimeConfig{
			HTTPTimeoutS:   120,
			PollIntervalMS: 500,
			PollTimeoutS:   60,
			Parallel:       4,
		},
		Profile: envOrDefault("E2E_PROFILE", "full"),
		Custom:  map[string]string{},
	}, nil
}

func parseEnv(data map[string]any) *Env {
	env := &Env{
		Runtime: RuntimeConfig{
			HTTPTimeoutS:   120,
			PollIntervalMS: 500,
			PollTimeoutS:   60,
			Parallel:       4,
		},
		Profile: "full",
		Custom:  map[string]string{},
	}

	if svc, ok := data["service"].(map[string]any); ok {
		env.Service.Name = strVal(svc, "name")
		env.Service.BaseURL = strings.TrimRight(strVal(svc, "base_url"), "/")
	}
	if auth, ok := data["auth"].(map[string]any); ok {
		env.Auth.Headers = make(map[string]string)
		if headers, ok := auth["headers"].(map[string]any); ok {
			for key, value := range headers {
				env.Auth.Headers[key] = fmt.Sprint(value)
			}
		}
	}
	if rt, ok := data["runtime"].(map[string]any); ok {
		if v := intVal(rt, "http_timeout_s"); v > 0 {
			env.Runtime.HTTPTimeoutS = v
		}
		if v := intVal(rt, "poll_interval_ms"); v > 0 {
			env.Runtime.PollIntervalMS = v
		}
		if v := intVal(rt, "poll_timeout_s"); v > 0 {
			env.Runtime.PollTimeoutS = v
		}
		if v := intVal(rt, "parallel"); v > 0 {
			env.Runtime.Parallel = v
		}
	}
	if p := strVal(data, "profile"); p != "" {
		env.Profile = p
	}
	if custom, ok := data["custom"].(map[string]any); ok {
		for k, v := range custom {
			env.Custom[k] = fmt.Sprint(v)
		}
	}
	return env
}

func authHeadersFromEnv() (map[string]string, error) {
	raw := os.Getenv("E2E_AUTH_HEADERS")
	if raw == "" {
		return map[string]string{}, nil
	}
	headers := map[string]string{}
	if err := json.Unmarshal([]byte(raw), &headers); err != nil {
		return nil, fmt.Errorf("parse E2E_AUTH_HEADERS as JSON object: %w", err)
	}
	return headers, nil
}

func strVal(m map[string]any, key string) string {
	if v, ok := m[key]; ok {
		return fmt.Sprint(v)
	}
	return ""
}

func intVal(m map[string]any, key string) int {
	v, ok := m[key]
	if !ok {
		return 0
	}
	switch n := v.(type) {
	case int:
		return n
	case float64:
		return int(n)
	case string:
		i, _ := strconv.Atoi(n)
		return i
	}
	return 0
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

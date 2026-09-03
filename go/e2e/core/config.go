// Package core provides configuration loading for e2e tests.
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

type Forge struct {
	Name string `yaml:"name"`
}

type Repository struct {
	Forge Forge  `yaml:"forge"`
	Path  string `yaml:"path"`
}

type Product struct {
	Name string `yaml:"name"`
}

type Component struct {
	Repository Repository `yaml:"repository"`
	Name       string     `yaml:"name"`
}

type Environment struct {
	Name string `yaml:"name"`
}

type KubernetesEnvironment struct {
	Environment `yaml:",inline"`
	Kubeconfig  string `yaml:"kubeconfig"`
	Context     string `yaml:"context,omitempty"`
}

type Service struct {
	Name        string                `yaml:"name"`
	Component   Component             `yaml:"component"`
	Environment KubernetesEnvironment `yaml:"environment"`
	BaseURL     string                `yaml:"base_url"`
	Headers     map[string]string     `yaml:"headers"`
}

// Operation is one named capability exposed by a Service.
type Operation struct {
	Name string `yaml:"name"`
}

// HTTPOperation is an Operation exposed through an HTTP method and path.
type HTTPOperation struct {
	Operation `yaml:",inline"`
	Method    string `yaml:"method"`
	Path      string `yaml:"path"`
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

type E2EConfig struct {
	Service      Service
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

// LoadConfig loads configuration from a YAML file with environment-variable interpolation.
// Falls back to environment variables if the file doesn't exist.
func LoadConfig(configPath string) (*E2EConfig, error) {
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
	if service, ok := resolved["service"].(map[string]any); ok {
		if headers, exists := service["headers"]; exists {
			if _, ok := headers.(map[string]any); !ok {
				return nil, fmt.Errorf("parse config %s: service.headers must be a mapping", configPath)
			}
		}
	}

	return parseConfig(resolved), nil
}

func loadFromEnvVars() (*E2EConfig, error) {
	headers, err := authHeadersFromEnv()
	if err != nil {
		return nil, err
	}
	return &E2EConfig{
		Service: Service{
			Name:    os.Getenv("E2E_SERVICE_NAME"),
			BaseURL: os.Getenv("E2E_BASE_URL"),
			Component: Component{
				Repository: Repository{
					Forge: Forge{Name: os.Getenv("E2E_FORGE")},
					Path:  os.Getenv("E2E_COMPONENT_REPOSITORY"),
				},
				Name: os.Getenv("E2E_COMPONENT_NAME"),
			},
			Environment: KubernetesEnvironment{
				Environment: Environment{Name: os.Getenv("E2E_ENVIRONMENT")},
				Kubeconfig:  os.Getenv("E2E_KUBECONFIG"),
				Context:     os.Getenv("E2E_KUBE_CONTEXT"),
			},
			Headers: headers,
		},
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

func parseConfig(data map[string]any) *E2EConfig {
	config := &E2EConfig{
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
		config.Service.Name = strVal(svc, "name")
		config.Service.BaseURL = strings.TrimRight(strVal(svc, "base_url"), "/")
		if component, ok := svc["component"].(map[string]any); ok {
			if repository, ok := component["repository"].(map[string]any); ok {
				config.Service.Component.Repository.Forge.Name = strVal(repository, "forge")
				config.Service.Component.Repository.Path = strVal(repository, "path")
			}
			config.Service.Component.Name = strVal(component, "name")
		}
		if environment, ok := svc["environment"].(map[string]any); ok {
			config.Service.Environment.Name = strVal(environment, "name")
			config.Service.Environment.Kubeconfig = strVal(environment, "kubeconfig")
			config.Service.Environment.Context = strVal(environment, "context")
		}
		config.Service.Headers = make(map[string]string)
		if headers, ok := svc["headers"].(map[string]any); ok {
			for key, value := range headers {
				config.Service.Headers[key] = fmt.Sprint(value)
			}
		}
	}
	if rt, ok := data["runtime"].(map[string]any); ok {
		if v := intVal(rt, "http_timeout_s"); v > 0 {
			config.Runtime.HTTPTimeoutS = v
		}
		if v := intVal(rt, "poll_interval_ms"); v > 0 {
			config.Runtime.PollIntervalMS = v
		}
		if v := intVal(rt, "poll_timeout_s"); v > 0 {
			config.Runtime.PollTimeoutS = v
		}
		if v := intVal(rt, "parallel"); v > 0 {
			config.Runtime.Parallel = v
		}
	}
	if p := strVal(data, "profile"); p != "" {
		config.Profile = p
	}
	if custom, ok := data["custom"].(map[string]any); ok {
		for k, v := range custom {
			config.Custom[k] = fmt.Sprint(v)
		}
	}
	return config
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

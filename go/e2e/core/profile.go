package core

import "testing"

// RequireProfile skips the test if env.Profile is not in the allowed set.
func RequireProfile(t *testing.T, env *Env, profiles ...string) {
	t.Helper()
	for _, p := range profiles {
		if env.Profile == p {
			return
		}
	}
	t.Skipf("profile=%q not in %v; skipping", env.Profile, profiles)
}

// RequireCapability skips the test if the server didn't report the named capability.
func RequireCapability(t *testing.T, env *Env, key string) {
	t.Helper()
	if !env.Capabilities.Known {
		t.Skipf("capabilities unknown; cannot confirm %q", key)
		return
	}
	if _, ok := env.Capabilities.Data[key]; !ok {
		t.Skipf("capability %q not available on this server", key)
	}
}

//go:build e2e

package sandbox_e2e

import (
	"os"
	"testing"

	"github.com/compforge/case-harness/go/e2e/suite"
)

var sandboxSuite = suite.New("sandbox-server")

func TestMain(m *testing.M) {
	os.Exit(sandboxSuite.Main(m.Run))
}

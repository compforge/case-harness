// Package suite collects CaseRun results into one durable e2e run.
package suite

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sync/atomic"
	"testing"
	"time"

	"github.com/compforge/case-harness/go/e2e/caserun"
	"github.com/compforge/case-harness/go/report"
)

var pathSegmentPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

type Option func(*Suite)

func WithRunsDir(path string) Option {
	return func(s *Suite) { s.runsDir = path }
}

func WithRunID(runID string) Option {
	return func(s *Suite) { s.runID = runID }
}

func WithOutput(writer io.Writer) Option {
	return func(s *Suite) { s.output = writer }
}

// Suite owns one e2e run identity and its aggregate Verdict. Business cases
// still own their typed state, lifecycle steps, and assertions.
type Suite struct {
	scope     string
	runsDir   string
	runID     string
	output    io.Writer
	recorder  caserun.Recorder
	count     atomic.Int64
	configErr error
}

func New(scope string, options ...Option) *Suite {
	s := &Suite{
		scope:   scope,
		runsDir: "runs",
		runID:   time.Now().UTC().Format("20060102T150405.000000000Z"),
		output:  os.Stderr,
	}
	for _, option := range options {
		option(s)
	}
	s.configErr = s.validateConfig()
	return s
}

func (s *Suite) validateConfig() error {
	if !pathSegmentPattern.MatchString(s.scope) {
		return fmt.Errorf("e2e suite scope %q is not a safe path segment", s.scope)
	}
	if !pathSegmentPattern.MatchString(s.runID) {
		return fmt.Errorf("e2e suite run id %q is not a safe path segment", s.runID)
	}
	return nil
}

// Assert records the CaseRun result before adapting it to testing.T. Recording
// first ensures fail, error, and skipped cases all remain visible in Verdict.
func (s *Suite) Assert(t *testing.T, result caserun.Result) {
	t.Helper()
	s.recorder.Record(result)
	s.count.Add(1)
	caserun.Assert(t, result)
}

// Finish writes runs/<scope>/<run-id>/verdict.json. A test selection that did
// not execute any CaseRun writes nothing rather than creating a misleading
// empty run.
func (s *Suite) Finish() (report.RunVerdict, string, error) {
	verdict := s.recorder.Verdict(s.scope, s.runID)
	if s.configErr != nil {
		return verdict, "", s.configErr
	}
	if s.count.Load() == 0 {
		return verdict, "", nil
	}
	path, err := report.WriteVerdict(filepath.Join(s.runsDir, s.scope, s.runID), verdict)
	return verdict, path, err
}

// Main wraps testing.M.Run for use from TestMain and makes Verdict persistence
// part of the suite result. It returns an exit code so the caller retains the
// required os.Exit ownership:
//
//	func TestMain(m *testing.M) { os.Exit(systemSuite.Main(m.Run)) }
func (s *Suite) Main(run func() int) int {
	if s.configErr != nil {
		fmt.Fprintf(s.output, "configure e2e suite: %v\n", s.configErr)
		return 1
	}
	code := run()
	_, path, err := s.Finish()
	if err != nil {
		fmt.Fprintf(s.output, "write e2e verdict: %v\n", err)
		if code == 0 {
			return 1
		}
		return code
	}
	if path != "" {
		fmt.Fprintf(s.output, "e2e verdict: %s\n", path)
	}
	return code
}

// Package contract implements the e2e "case lives next to the handler" workflow:
// +case / +spec marker comments on handler funcs → discover (go/ast
// scan) → scaffold (*_e2e_test.go generation) → meta block + case_hash drift
// detection.
//
// It is the Go counterpart of python/e2e_harness/api. Discovery is pure static
// AST analysis: the scanned service is never imported or run, so the markers
// cost nothing at build time and work even when the service does not compile.
//
// The marker grammar is owned by spec-case and borrows kubebuilder's convention:
// a "+" prefix and a single-line "name:key=value" form, which sidesteps the
// gofmt doc-comment reflow that multi-line continuations suffer.
package contract

import (
	"fmt"
	"strings"

	"github.com/compforge/spec-case/toolchains/go/marker"
)

// DefaultGroup is the test bucket used when a case omits group=. Generated tests
// land under <test_root>/<group>/, one Go package per group.
const DefaultGroup = "e2e"

// Case is one declared test intention, parsed from a handler's +case marker
// (and the handler's +spec). It carries only authoring-time intent — no
// environment, no experiment parameters — matching the canonical case spec.
type Case struct {
	ID       string // immutable, group-unique slug
	Desc     string // one-line human description
	Input    string // natural-language: request shape / params
	Expect   string // natural-language: expected outcome
	Forbid   string // natural-language: what must NOT happen
	Group    string // test bucket (subdir); DefaultGroup if unset
	Endpoint string // handler function name the case hangs off
	SpecText string // handler +spec text (shared by all its cases)
}

// parseDoc adapts spec-case's canonical marker grammar to case-harness's
// generated-test organization fields.
//
// It extracts the +spec text and the ordered +case list from one
// handler's doc comment. Each marker is a single line:
//
//	+spec=`tenant_id required; concurrent starts join in-flight`
//	+case:id=happy,desc=`minimal create succeeds`,expect=`200; name non-empty`
//
// Free-form field values are backtick- or quote-wrapped so embedded commas and
// semicolons survive. Invalid +case markers are rejected so casegen check cannot
// silently turn a malformed test intention into missing coverage.
func parseDoc(doc string) (specText string, cases []Case, err error) {
	parsed := marker.Parse(doc)
	for lineNo, raw := range strings.Split(doc, "\n") {
		line := strings.TrimSpace(raw)
		if !strings.HasPrefix(line, "+case:") {
			continue
		}
		if len(marker.Parse(line).Cases) != 1 {
			return "", nil, fmt.Errorf("invalid +case marker on doc line %d: %s", lineNo+1, line)
		}
	}
	for _, c := range parsed.Cases {
		group := c.Group
		if group == "" {
			group = DefaultGroup
		}
		cases = append(cases, Case{
			ID: c.ID, Desc: c.Desc,
			Input: c.Input, Expect: c.Expect, Forbid: c.Forbid,
			Group: group,
		})
	}
	return parsed.Spec, cases, nil
}

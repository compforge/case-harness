// Package contract implements the e2e "case lives next to the handler" workflow:
// +e2e:case / +e2e:spec marker comments on handler funcs → discover (go/ast
// scan) → scaffold (*_e2e_test.go generation) → meta block + case_hash drift
// detection.
//
// It is the Go counterpart of python/e2e_harness/api. Discovery is pure static
// AST analysis: the scanned service is never imported or run, so the markers
// cost nothing at build time and work even when the service does not compile.
//
// The marker grammar borrows kubebuilder's convention — a "+" prefix and a
// single-line "name:key=value" form (which sidesteps the gofmt doc-comment
// reflow that multi-line continuations suffer) — but parses it directly here
// rather than depending on controller-tools, whose typed engine buys little for
// these all-string fields and would drag in a large dependency tree.
package contract

import (
	"regexp"
	"strings"
)

// DefaultGroup is the test bucket used when a case omits group=. Generated tests
// land under <test_root>/<group>/, one Go package per group.
const DefaultGroup = "e2e"

// caseIDPattern constrains ids to a stable, file-name-safe slug — it doubles as
// the cross-run/cross-harness primary key, so it must be immutable and unique.
var caseIDPattern = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// Case is one declared test intention, parsed from a handler's +e2e:case marker
// (and the handler's +e2e:spec). It carries only authoring-time intent — no
// environment, no experiment parameters — matching the canonical case spec.
type Case struct {
	ID       string // immutable, group-unique slug
	Desc     string // one-line human description
	Input    string // natural-language: request shape / params
	Expect   string // natural-language: expected outcome
	Forbid   string // natural-language: what must NOT happen
	Group    string // test bucket (subdir); DefaultGroup if unset
	Endpoint string // handler function name the case hangs off
	SpecText string // handler +e2e:spec text (shared by all its cases)
}

// parseDoc extracts the +e2e:spec text and the ordered +e2e:case list from one
// handler's doc comment. Each marker is a single line:
//
//	+e2e:spec=`tenant_id required; concurrent starts join in-flight`
//	+e2e:case:id=happy,desc=`minimal create succeeds`,expect=`200; name non-empty`
//
// Free-form field values are backtick- or quote-wrapped so embedded commas and
// semicolons survive. A +e2e:case with a malformed id is skipped; casegen check
// surfaces missing coverage another way.
func parseDoc(doc string) (specText string, cases []Case) {
	for _, raw := range strings.Split(doc, "\n") {
		line := strings.TrimSpace(raw)
		switch {
		case strings.HasPrefix(line, "+e2e:case:"):
			args := parseMarkerArgs(strings.TrimPrefix(line, "+e2e:case:"))
			if !caseIDPattern.MatchString(args["id"]) {
				continue
			}
			group := args["group"]
			if group == "" {
				group = DefaultGroup
			}
			cases = append(cases, Case{
				ID: args["id"], Desc: args["desc"],
				Input: args["input"], Expect: args["expect"], Forbid: args["forbid"],
				Group: group,
			})
		case strings.HasPrefix(line, "+e2e:spec="):
			specText = unquote(strings.TrimPrefix(line, "+e2e:spec="))
		}
	}
	return specText, cases
}

// parseMarkerArgs splits a "key=value,key=value" arg string. A value may be
// backtick- or double-quote-wrapped, in which case embedded commas/semicolons
// are literal; an unquoted value runs to the next comma.
func parseMarkerArgs(s string) map[string]string {
	args := map[string]string{}
	for i, n := 0, len(s); i < n; {
		for i < n && (s[i] == ',' || s[i] == ' ') {
			i++
		}
		keyStart := i
		for i < n && s[i] != '=' {
			i++
		}
		if i >= n {
			break // no '=' → malformed tail, stop
		}
		key := strings.TrimSpace(s[keyStart:i])
		i++ // skip '='
		var val string
		if i < n && (s[i] == '`' || s[i] == '"') {
			q := s[i]
			i++
			start := i
			for i < n && s[i] != q {
				i++
			}
			val = s[start:i]
			if i < n {
				i++ // skip closing quote
			}
		} else {
			start := i
			for i < n && s[i] != ',' {
				i++
			}
			val = strings.TrimSpace(s[start:i])
		}
		if key != "" {
			args[key] = val
		}
	}
	return args
}

// unquote strips a single layer of matching backtick or double quotes.
func unquote(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 2 && (s[0] == '`' || s[0] == '"') && s[len(s)-1] == s[0] {
		return s[1 : len(s)-1]
	}
	return s
}

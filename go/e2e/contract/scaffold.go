package contract

import (
	"fmt"
	"regexp"
	"strings"
	"time"
)

// The framework owns two regions of every generated file, both above the package
// clause: the doc block (rendered from the case) and the meta block (case_id +
// hash). Everything from `package` down — imports and the test body — is owned by
// whoever fills the test in, and is preserved verbatim on re-sync.
//
// RenderNew produces a fresh file; UpdateStale rewrites only the owned regions of
// an existing one and drops a STALE marker so the next reader re-checks the body.

const buildTag = "//go:build e2e"

// RenderNew renders a complete *_e2e_test.go for a freshly discovered case.
func RenderNew(dc DiscoveredCase) string {
	return strings.Join([]string{
		buildTag,
		"",
		renderDoc(dc, ""),
		"",
		renderMeta(dc.Case, dc.Hash),
		"",
		"package " + pkgName(dc.Case.Group),
		"",
		renderBody(dc.Case),
	}, "\n") + "\n"
}

// UpdateStale rewrites the doc + meta regions of an existing file to match the
// current case, inserts a STALE marker into the doc, and keeps the package clause
// and everything below it untouched.
func UpdateStale(content string, dc DiscoveredCase, now time.Time) string {
	body := bodyFrom(content)
	stale := fmt.Sprintf("STALE (%s): case or +spec changed; re-check the test body against the doc above.",
		now.UTC().Format("2006-01-02T15:04:05Z"))
	return strings.Join([]string{
		buildTag,
		"",
		renderDoc(dc, stale),
		"",
		renderMeta(dc.Case, dc.Hash),
		"",
		body,
	}, "\n")
}

// bodyFrom returns the file from its `package` clause onward (the human-owned
// region). If no package clause is found, the whole content is treated as body.
func bodyFrom(content string) string {
	for _, idx := range packageLineIdx(content) {
		return content[idx:]
	}
	return content
}

var packageRe = regexp.MustCompile(`(?m)^package\s+\w+`)

func packageLineIdx(content string) []int {
	if loc := packageRe.FindStringIndex(content); loc != nil {
		return []int{loc[0]}
	}
	return nil
}

func renderDoc(dc DiscoveredCase, stale string) string {
	c := dc.Case
	var b strings.Builder
	line := func(s string) {
		if s == "" {
			b.WriteString("//\n")
			return
		}
		b.WriteString("// " + s + "\n")
	}
	if stale != "" {
		line(stale)
		line("")
	}
	line(fmt.Sprintf("%s__%s — %s", c.Endpoint, c.ID, c.Desc))
	if c.Input != "" {
		line("")
		line("input:")
		writeField(line, c.Input)
	}
	if c.Expect != "" {
		line("")
		line("expect:")
		writeField(line, c.Expect)
	}
	if c.Forbid != "" {
		line("")
		line("forbid:")
		writeField(line, c.Forbid)
	}
	line("")
	if c.SpecText != "" {
		line("spec:")
		writeField(line, c.SpecText)
	} else {
		line("spec: <handler has no +spec; consider adding one>")
	}
	line("")
	line(fmt.Sprintf("handler: %s %s", dc.SourceFile, c.Endpoint))
	line(fmt.Sprintf("source:  +case:id=%s", c.ID))
	return strings.TrimRight(b.String(), "\n")
}

func writeField(line func(string), text string) {
	for _, l := range strings.Split(text, "\n") {
		line("  " + l)
	}
}

func renderBody(c Case) string {
	return strings.Join([]string{
		"import (",
		"\t\"context\"",
		"\t\"testing\"",
		"\t\"time\"",
		"",
		"\t\"github.com/compforge/case-harness/go/e2e/core\"",
		"\t\"github.com/compforge/case-harness/go/e2e/judge\"",
		"\t\"github.com/compforge/case-harness/go/e2e/runner\"",
		")",
		"",
		fmt.Sprintf("func Test_%s__%s(t *testing.T) {", c.Endpoint, c.ID),
		"\tenv, err := core.LoadEnv(\"config.yaml\")",
		"\tif err != nil {",
		"\t\tt.Fatalf(\"load env: %v\", err)",
		"\t}",
		"\tr := runner.NewJSONRunner(env)",
		"\tctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)",
		"\tdefer cancel()",
		"",
		"\t// TODO(casegen): build the request, fire it, and assert per the doc above.",
		"\t// outcome := r.Trigger(t, ctx, runner.Request{",
		"\t// \tMethod: \"POST\", Path: \"/...\",",
		"\t// \tBody:   map[string]any{},",
		"\t// })",
		"\t// judge.Assert(t, outcome, judge.Status2xx())",
		"\t_ = r",
		"\t_ = ctx",
		"\t_ = judge.Status2xx",
		"\tt.Skip(\"casegen scaffold: fill in the test body\")",
		"}",
	}, "\n")
}

var identUnsafe = regexp.MustCompile(`[^a-zA-Z0-9_]`)

// pkgName turns a group name into a valid Go package identifier.
func pkgName(group string) string {
	s := identUnsafe.ReplaceAllString(group, "_")
	if s == "" {
		s = DefaultGroup
	}
	if s[0] >= '0' && s[0] <= '9' {
		s = "g_" + s
	}
	return s
}

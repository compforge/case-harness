package contract

import (
	"bufio"
	"regexp"
	"strings"
)

// Meta block format in generated *_e2e_test.go files (delimited so the parser is
// deterministic; it sits between the build tag and the package clause):
//
//	// e2e-meta-start
//	// case_id:   happy_minimal
//	// case_hash: a1b2c3d4
//	// e2e-meta-end
//
// Only two fields — the test's stable API-contract identity (case_id) and its
// content fingerprint (case_hash). The file's endpoint-oriented name is a
// presentation detail and may survive an internal handler rename.
const (
	metaStart = "// e2e-meta-start"
	metaEnd   = "// e2e-meta-end"
)

var metaLine = regexp.MustCompile(`^//\s*(case_id|case_hash)\s*:\s*(.+?)\s*$`)

// ScriptMeta is the identity parsed back out of a generated test file.
type ScriptMeta struct {
	CaseID   string
	CaseHash string
}

// parseMeta scans a generated file's contents for its meta block. Returns
// (nil, false) when no block is present (e.g. a hand-written test).
func parseMeta(content string) (*ScriptMeta, bool) {
	sc := bufio.NewScanner(strings.NewReader(content))
	inBlock := false
	var m ScriptMeta
	found := false
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		switch {
		case line == metaStart:
			inBlock = true
		case line == metaEnd:
			if found {
				return &m, true
			}
			return nil, false
		case inBlock:
			if g := metaLine.FindStringSubmatch(line); g != nil {
				found = true
				if g[1] == "case_id" {
					m.CaseID = g[2]
				} else {
					m.CaseHash = g[2]
				}
			}
		}
	}
	return nil, false
}

func renderMeta(c Case, hash string) string {
	return strings.Join([]string{
		metaStart,
		"// case_id:   " + c.ID,
		"// case_hash: " + hash,
		metaEnd,
	}, "\n")
}

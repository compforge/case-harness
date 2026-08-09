package contract

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
)

// DiscoverConfig points discovery at the service source and the test output tree.
type DiscoverConfig struct {
	SourceRoot string // dir scanned for handlers carrying +case/+spec
	TestRoot   string // where generated *_e2e_test.go land, grouped by case.Group
}

// DiscoveredCase is one case resolved against the filesystem: the parsed Case,
// its content hash, the handler source file (relative to SourceRoot), and the
// absolute path of the test file that should embody it.
type DiscoveredCase struct {
	Case       Case
	Hash       string
	SourceFile string
	TargetPath string
}

// Discover walks SourceRoot, parses every non-test .go file's comments with the
// standard go/ast toolchain, and returns one DiscoveredCase per +case found.
//
// Parsing is comment-only and tolerant: a file that fails to parse is skipped
// rather than aborting the scan, so a half-written handler never blocks
// discovering the rest. Results are sorted by target path for stable output.
func Discover(cfg DiscoverConfig) ([]DiscoveredCase, error) {
	var out []DiscoveredCase
	fset := token.NewFileSet()

	err := filepath.WalkDir(cfg.SourceRoot, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			// Never skip the scan root itself — only nested noise dirs.
			if p != cfg.SourceRoot && skipDir(d.Name()) {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		f, perr := parser.ParseFile(fset, p, nil, parser.ParseComments)
		if perr != nil {
			return nil
		}
		rel, _ := filepath.Rel(cfg.SourceRoot, p)
		for _, decl := range f.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok || fn.Doc == nil {
				continue
			}
			spec, cases := parseDoc(fn.Doc.Text())
			for _, c := range cases {
				c.Endpoint = fn.Name.Name
				c.SpecText = spec
				out = append(out, DiscoveredCase{
					Case:       c,
					Hash:       CaseHash(c),
					SourceFile: rel,
					TargetPath: targetPath(cfg.TestRoot, c),
				})
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if err := checkCollisions(out); err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].TargetPath < out[j].TargetPath })
	return out, nil
}

// targetPath keys the test file by group (not by source layout), so handlers can
// be reorganized without moving tests: <test_root>/<group>/<endpoint>__<id>_e2e_test.go.
func targetPath(testRoot string, c Case) string {
	return filepath.Join(testRoot, c.Group, fmt.Sprintf("%s__%s_e2e_test.go", c.Endpoint, c.ID))
}

func checkCollisions(cases []DiscoveredCase) error {
	seen := map[string]string{}
	for _, dc := range cases {
		owner := dc.Case.Endpoint + "/" + dc.Case.ID
		identity := dc.Case.Group + "/" + dc.Case.ID
		if prev, ok := seen[identity]; ok {
			return fmt.Errorf("case identity collision: %s declared by both %s and %s",
				identity, prev, owner)
		}
		seen[identity] = owner
	}
	return nil
}

func skipDir(name string) bool {
	switch name {
	case "vendor", "testdata", "node_modules":
		return true
	}
	return strings.HasPrefix(name, ".")
}

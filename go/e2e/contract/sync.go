package contract

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Action is what sync would do (or did) to a case's test file.
type Action string

const (
	ActionCreate  Action = "create"  // no test file yet
	ActionStale   Action = "stale"   // file exists but its hash no longer matches
	ActionPending Action = "pending" // scaffold or stale body still needs human review
	ActionRefresh Action = "refresh" // only the framework-owned header is outdated
	ActionOrphan  Action = "orphan"  // generated file has no corresponding +case marker
	ActionOK      Action = "ok"      // file in sync
)

// SyncResult pairs a discovered case with its classification.
type SyncResult struct {
	Case   DiscoveredCase
	Action Action
}

// Plan reconciles discovered markers with managed test files in both directions.
// `casegen check` uses it as a CI gate: only ActionOK is fully synchronized.
func Plan(testRoot string, cases []DiscoveredCase) ([]SyncResult, error) {
	managed, err := scanManagedTests(testRoot)
	if err != nil {
		return nil, err
	}
	byIdentity := make(map[string]managedTest, len(managed))
	for _, test := range managed {
		key := managedIdentity(filepath.Dir(test.path), test.meta.CaseID)
		if previous, ok := byIdentity[key]; ok {
			return nil, fmt.Errorf("duplicate case_id %q in %s and %s",
				test.meta.CaseID, previous.path, test.path)
		}
		byIdentity[key] = test
	}

	out := make([]SyncResult, 0, len(cases))
	active := make(map[string]bool, len(cases))
	for _, dc := range cases {
		key := managedIdentity(filepath.Dir(dc.TargetPath), dc.Case.ID)
		active[key] = true
		content, err := os.ReadFile(dc.TargetPath)
		if errors.Is(err, fs.ErrNotExist) {
			existing, found := byIdentity[key]
			if !found {
				out = append(out, SyncResult{dc, ActionCreate})
				continue
			}
			// The endpoint and its presentation filename may change during an
			// internal refactor. The meta case_id is the stable API-contract
			// identity, so keep using the existing human-owned test file.
			dc.TargetPath = existing.path
			content = existing.content
			err = nil
		}
		if err != nil {
			return nil, err
		}
		meta, ok := parseMeta(string(content))
		if ok && meta.CaseID != dc.Case.ID {
			return nil, fmt.Errorf("case target %s belongs to %q, not %q", dc.TargetPath, meta.CaseID, dc.Case.ID)
		}
		if !ok || meta.CaseHash != dc.Hash {
			out = append(out, SyncResult{dc, ActionStale})
			continue
		}
		if needsManualReview(string(content)) {
			out = append(out, SyncResult{dc, ActionPending})
			continue
		}
		if !ownedHeaderMatches(string(content), dc) {
			out = append(out, SyncResult{dc, ActionRefresh})
			continue
		}
		out = append(out, SyncResult{dc, ActionOK})
	}
	for _, test := range managed {
		key := managedIdentity(filepath.Dir(test.path), test.meta.CaseID)
		if active[key] {
			continue
		}
		out = append(out, SyncResult{
			Case: DiscoveredCase{
				Case:       Case{ID: test.meta.CaseID},
				Hash:       test.meta.CaseHash,
				TargetPath: test.path,
			},
			Action: ActionOrphan,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Case.TargetPath < out[j].Case.TargetPath })
	return out, nil
}

type managedTest struct {
	path    string
	content []byte
	meta    *ScriptMeta
}

func scanManagedTests(testRoot string) ([]managedTest, error) {
	var out []managedTest
	err := filepath.WalkDir(testRoot, func(path string, entry fs.DirEntry, walkErr error) error {
		if errors.Is(walkErr, fs.ErrNotExist) {
			return nil
		}
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), "_e2e_test.go") {
			return nil
		}
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		text := string(content)
		meta, ok := parseMeta(text)
		if !ok {
			if strings.Contains(text, metaStart) || strings.Contains(text, metaEnd) {
				return fmt.Errorf("invalid e2e meta block in %s", path)
			}
			return nil
		}
		if meta.CaseID == "" || meta.CaseHash == "" {
			return fmt.Errorf("incomplete e2e meta block in %s", path)
		}
		out = append(out, managedTest{path: path, content: content, meta: meta})
		return nil
	})
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	return out, err
}

func managedIdentity(dir, caseID string) string {
	return filepath.Clean(dir) + "\x00" + caseID
}

// Apply writes create, stale, and metadata-refresh results to disk and returns
// only the ones it changed.
func Apply(results []SyncResult, now time.Time) ([]SyncResult, error) {
	var changed []SyncResult
	for _, r := range results {
		switch r.Action {
		case ActionCreate:
			if err := os.MkdirAll(filepath.Dir(r.Case.TargetPath), 0o755); err != nil {
				return changed, err
			}
			if err := os.WriteFile(r.Case.TargetPath, []byte(RenderNew(r.Case)), 0o644); err != nil {
				return changed, err
			}
			changed = append(changed, r)
		case ActionStale:
			content, err := os.ReadFile(r.Case.TargetPath)
			if err != nil {
				return changed, err
			}
			updated := UpdateStale(string(content), r.Case, now)
			if err := os.WriteFile(r.Case.TargetPath, []byte(updated), 0o644); err != nil {
				return changed, err
			}
			changed = append(changed, r)
		case ActionRefresh:
			content, err := os.ReadFile(r.Case.TargetPath)
			if err != nil {
				return changed, err
			}
			if err := os.WriteFile(r.Case.TargetPath, []byte(RefreshOwned(string(content), r.Case)), 0o644); err != nil {
				return changed, err
			}
			changed = append(changed, r)
		}
	}
	return changed, nil
}

package contract

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Action is what sync would do (or did) to a case's test file.
type Action string

const (
	ActionCreate Action = "create" // no test file yet
	ActionStale  Action = "stale"  // file exists but its hash no longer matches
	ActionOK     Action = "ok"     // file in sync
)

// SyncResult pairs a discovered case with its classification.
type SyncResult struct {
	Case   DiscoveredCase
	Action Action
}

// Plan classifies each discovered case against what is on disk, without writing.
// `casegen check` uses this directly as a CI gate (any create/stale ⇒ drift).
func Plan(cases []DiscoveredCase) ([]SyncResult, error) {
	out := make([]SyncResult, 0, len(cases))
	for _, dc := range cases {
		content, err := os.ReadFile(dc.TargetPath)
		if errors.Is(err, fs.ErrNotExist) {
			path, existing, found, findErr := findExistingByCaseID(filepath.Dir(dc.TargetPath), dc.Case.ID)
			if findErr != nil {
				return nil, findErr
			}
			if !found {
				out = append(out, SyncResult{dc, ActionCreate})
				continue
			}
			// The endpoint and its presentation filename may change during an
			// internal refactor. The meta case_id is the stable API-contract
			// identity, so keep using the existing human-owned test file.
			dc.TargetPath = path
			content = existing
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
		out = append(out, SyncResult{dc, ActionOK})
	}
	return out, nil
}

func findExistingByCaseID(dir, caseID string) (string, []byte, bool, error) {
	entries, err := os.ReadDir(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return "", nil, false, nil
	}
	if err != nil {
		return "", nil, false, err
	}

	var matchPath string
	var matchContent []byte
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), "_e2e_test.go") {
			continue
		}
		path := filepath.Join(dir, entry.Name())
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return "", nil, false, readErr
		}
		meta, ok := parseMeta(string(content))
		if !ok || meta.CaseID != caseID {
			continue
		}
		if matchPath != "" {
			return "", nil, false, fmt.Errorf("duplicate case_id %q in %s and %s", caseID, matchPath, path)
		}
		matchPath = path
		matchContent = content
	}
	return matchPath, matchContent, matchPath != "", nil
}

// Apply writes create/stale results to disk (ok results are left untouched) and
// returns only the ones it changed.
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
		}
	}
	return changed, nil
}

package contract

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
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
			out = append(out, SyncResult{dc, ActionCreate})
			continue
		}
		if err != nil {
			return nil, err
		}
		meta, ok := parseMeta(string(content))
		if !ok || meta.CaseHash != dc.Hash {
			out = append(out, SyncResult{dc, ActionStale})
			continue
		}
		out = append(out, SyncResult{dc, ActionOK})
	}
	return out, nil
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

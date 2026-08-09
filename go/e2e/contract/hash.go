package contract

import (
	"github.com/compforge/spec-case/toolchains/go/marker"
)

// CaseHash fingerprints a case's authoring intent: id, desc, the three
// natural-language fields, and the handler +spec. The generated test file stores
// it in its meta block; when discover recomputes a different hash, the case or
// spec drifted underneath the (human-edited) test body, and sync marks it STALE.
//
// Keep the field set and order stable — changing it invalidates every stored hash.
func CaseHash(c Case) string {
	return marker.IntentHash(marker.Case{
		ID: c.ID, Desc: c.Desc, Input: c.Input, Expect: c.Expect, Forbid: c.Forbid, Group: c.Group,
	}, c.SpecText)
}

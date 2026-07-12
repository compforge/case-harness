package contract

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

// CaseHash fingerprints a case's authoring intent: id, desc, the three
// natural-language fields, and the handler @spec. The generated test file stores
// it in its meta block; when discover recomputes a different hash, the case or
// spec drifted underneath the (human-edited) test body, and sync marks it STALE.
//
// Keep the field set and order stable — changing it invalidates every stored hash.
func CaseHash(c Case) string {
	h := sha256.Sum256([]byte(strings.Join([]string{
		c.ID, c.Desc, c.Input, c.Expect, c.Forbid, c.SpecText,
	}, "\x00")))
	return hex.EncodeToString(h[:])[:8]
}

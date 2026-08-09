package contract

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseDoc(t *testing.T) {
	doc := strings.Join([]string{
		"StartSandbox creates a sandbox.",
		"",
		"+spec=`tenant_id required; concurrent starts join in-flight`",
		"+case:id=happy_minimal,desc=`minimal create succeeds`,input=`POST /start`,expect=`200; sandbox_name non-empty`,forbid=`more than one pod`",
		"+case:id=dup_conv,desc=`reuse same pod`,group=sandbox",
		"+case:id=Bad-ID,desc=`should be skipped`",
	}, "\n")

	spec, cases := parseDoc(doc)
	if !strings.Contains(spec, "tenant_id required") {
		t.Fatalf("spec not captured: %q", spec)
	}
	if len(cases) != 2 {
		t.Fatalf("want 2 valid cases (Bad-ID skipped), got %d: %+v", len(cases), cases)
	}
	hm := cases[0]
	if hm.ID != "happy_minimal" || hm.Desc != "minimal create succeeds" {
		t.Errorf("case[0] id/desc wrong: %+v", hm)
	}
	if hm.Input != "POST /start" || hm.Expect != "200; sandbox_name non-empty" || hm.Forbid != "more than one pod" {
		t.Errorf("case[0] fields wrong: %+v", hm)
	}
	if hm.Group != DefaultGroup {
		t.Errorf("case[0] group = %q, want default %q", hm.Group, DefaultGroup)
	}
	if cases[1].Group != "sandbox" {
		t.Errorf("case[1] group = %q, want sandbox", cases[1].Group)
	}
}

func TestCaseHashStableAndSensitive(t *testing.T) {
	c := Case{ID: "x", Desc: "d", Input: "i", Expect: "e", Forbid: "f", SpecText: "s"}
	h1 := CaseHash(c)
	if h1 != CaseHash(c) {
		t.Fatal("hash not deterministic")
	}
	if len(h1) != 8 {
		t.Fatalf("hash len = %d, want 8", len(h1))
	}
	c2 := c
	c2.Expect = "different"
	if CaseHash(c2) == h1 {
		t.Fatal("hash should change when a field changes")
	}
}

func TestDiscoverFixture(t *testing.T) {
	cases, err := Discover(DiscoverConfig{SourceRoot: "testdata/src", TestRoot: "/tmp/out"})
	if err != nil {
		t.Fatalf("discover: %v", err)
	}
	got := map[string]DiscoveredCase{}
	for _, dc := range cases {
		got[dc.Case.ID] = dc
	}
	for _, id := range []string{"happy_minimal", "dup_conv", "missing_tenant"} {
		if _, ok := got[id]; !ok {
			t.Errorf("missing discovered case %q (got %d total)", id, len(cases))
		}
	}
	hm := got["happy_minimal"]
	if hm.Case.Endpoint != "StartSandbox" {
		t.Errorf("endpoint = %q, want StartSandbox", hm.Case.Endpoint)
	}
	if !strings.Contains(hm.Case.SpecText, "tenant_id required") {
		t.Errorf("spec not attached: %q", hm.Case.SpecText)
	}
	if !strings.HasSuffix(hm.TargetPath, "/e2e/StartSandbox__happy_minimal_e2e_test.go") {
		t.Errorf("target path = %q", hm.TargetPath)
	}
	if !strings.HasSuffix(got["dup_conv"].TargetPath, "/sandbox/StartSandbox__dup_conv_e2e_test.go") {
		t.Errorf("dup_conv target path = %q", got["dup_conv"].TargetPath)
	}
}

func TestRenderNewRoundtripsMeta(t *testing.T) {
	dc := DiscoveredCase{
		Case: Case{ID: "happy_minimal", Desc: "ok", Group: DefaultGroup, Endpoint: "StartSandbox", SpecText: "x"},
		Hash: "abcd1234",
	}
	out := RenderNew(dc)
	if !strings.HasPrefix(out, "//go:build e2e\n") {
		t.Error("missing build tag")
	}
	if !strings.Contains(out, "package e2e\n") {
		t.Error("missing package clause")
	}
	if !strings.Contains(out, "func Test_StartSandbox__happy_minimal(") {
		t.Error("missing test func")
	}
	meta, ok := parseMeta(out)
	if !ok || meta.CaseID != "happy_minimal" || meta.CaseHash != "abcd1234" {
		t.Fatalf("meta roundtrip failed: ok=%v meta=%+v", ok, meta)
	}
}

func TestUpdateStalePreservesBody(t *testing.T) {
	dc := DiscoveredCase{
		Case: Case{ID: "happy_minimal", Desc: "ok", Group: DefaultGroup, Endpoint: "StartSandbox"},
		Hash: "old00000",
	}
	original := RenderNew(dc)
	// Simulate a human editing the body.
	edited := strings.Replace(original,
		`t.Skip("casegen scaffold: fill in the test body")`,
		`t.Log("human-written assertion")`, 1)
	if edited == original {
		t.Fatal("failed to simulate body edit")
	}

	dc.Hash = "new11111"
	dc.Case.Desc = "ok, revised"
	updated := UpdateStale(edited, dc, time.Unix(0, 0))

	if !strings.Contains(updated, `t.Log("human-written assertion")`) {
		t.Error("body edit was not preserved")
	}
	if !strings.Contains(updated, "STALE (1970-01-01T00:00:00Z)") {
		t.Error("STALE marker not inserted")
	}
	meta, ok := parseMeta(updated)
	if !ok || meta.CaseHash != "new11111" {
		t.Fatalf("meta not refreshed: ok=%v meta=%+v", ok, meta)
	}
	if !strings.Contains(updated, "ok, revised") {
		t.Error("doc not refreshed with new desc")
	}
}

func TestPlanKeepsExistingFileAcrossEndpointRename(t *testing.T) {
	root := t.TempDir()
	original := Case{
		ID: "happy_minimal", Desc: "ok", Group: DefaultGroup,
		Endpoint: "OldHandler", SpecText: "stable API contract",
	}
	existingPath := targetPath(root, original)
	if err := os.MkdirAll(filepath.Dir(existingPath), 0o755); err != nil {
		t.Fatal(err)
	}
	hash := CaseHash(original)
	if err := os.WriteFile(existingPath, []byte(RenderNew(DiscoveredCase{Case: original, Hash: hash})), 0o644); err != nil {
		t.Fatal(err)
	}

	renamed := original
	renamed.Endpoint = "NewHandler"
	plan, err := Plan([]DiscoveredCase{{
		Case:       renamed,
		Hash:       CaseHash(renamed),
		TargetPath: targetPath(root, renamed),
	}})
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if len(plan) != 1 || plan[0].Action != ActionOK {
		t.Fatalf("plan = %+v, want one ok result", plan)
	}
	if plan[0].Case.TargetPath != existingPath {
		t.Fatalf("target path = %q, want existing %q", plan[0].Case.TargetPath, existingPath)
	}
}

func TestCheckCollisionsUsesStableCaseIdentity(t *testing.T) {
	err := checkCollisions([]DiscoveredCase{
		{Case: Case{ID: "same", Group: DefaultGroup, Endpoint: "HandlerA"}, TargetPath: "/tmp/HandlerA__same_e2e_test.go"},
		{Case: Case{ID: "same", Group: DefaultGroup, Endpoint: "HandlerB"}, TargetPath: "/tmp/HandlerB__same_e2e_test.go"},
	})
	if err == nil || !strings.Contains(err.Error(), "case identity collision") {
		t.Fatalf("checkCollisions() error = %v, want case identity collision", err)
	}
}

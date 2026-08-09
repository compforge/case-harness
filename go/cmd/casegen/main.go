// Command casegen discovers +case/+spec markers on handler functions and
// keeps the generated *_e2e_test.go files in sync with them.
//
//	casegen list  --source ./internal/api
//	casegen sync  --source ./internal/api --test ./tests/e2e
//	casegen check --source ./internal/api --test ./tests/e2e   # CI gate
//
// Discovery is pure static AST analysis — the scanned service is never imported
// or run. See go/e2e/contract for the mechanism.
package main

import (
	"flag"
	"fmt"
	"os"
	"text/tabwriter"
	"time"

	"github.com/compforge/case-harness/go/e2e/contract"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "list":
		os.Exit(cmdList(os.Args[2:]))
	case "sync":
		os.Exit(cmdSync(os.Args[2:]))
	case "check":
		os.Exit(cmdCheck(os.Args[2:]))
	case "-h", "--help", "help":
		usage()
		os.Exit(0)
	default:
		fmt.Fprintf(os.Stderr, "casegen: unknown subcommand %q\n\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `casegen — discover +case markers and sync e2e test scaffolds

usage:
  casegen list  --source DIR
  casegen sync  --source DIR --test DIR
  casegen check --source DIR --test DIR

  list   print every +case found under --source
  sync   create missing test files; mark drifted ones STALE
  check  exit non-zero if any case is missing or drifted (no writes)
`)
}

func discover(args []string, needTest bool) (contract.DiscoverConfig, []contract.DiscoveredCase, int) {
	fs := flag.NewFlagSet("casegen", flag.ExitOnError)
	source := fs.String("source", "", "dir to scan for +case/+spec handlers (required)")
	test := fs.String("test", "", "dir where generated *_e2e_test.go land")
	_ = fs.Parse(args)

	if *source == "" {
		fmt.Fprintln(os.Stderr, "casegen: --source is required")
		return contract.DiscoverConfig{}, nil, 2
	}
	if needTest && *test == "" {
		fmt.Fprintln(os.Stderr, "casegen: --test is required")
		return contract.DiscoverConfig{}, nil, 2
	}
	cfg := contract.DiscoverConfig{SourceRoot: *source, TestRoot: *test}
	cases, err := contract.Discover(cfg)
	if err != nil {
		fmt.Fprintf(os.Stderr, "casegen: discover: %v\n", err)
		return cfg, nil, 1
	}
	return cfg, cases, 0
}

func cmdList(args []string) int {
	_, cases, code := discover(args, false)
	if code != 0 {
		return code
	}
	w := tabwriter.NewWriter(os.Stdout, 0, 4, 2, ' ', 0)
	fmt.Fprintln(w, "GROUP\tENDPOINT\tCASE\tHASH\tHANDLER")
	for _, dc := range cases {
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\n",
			dc.Case.Group, dc.Case.Endpoint, dc.Case.ID, dc.Hash, dc.SourceFile)
	}
	w.Flush()
	fmt.Printf("\n%d case(s)\n", len(cases))
	return 0
}

func cmdSync(args []string) int {
	_, cases, code := discover(args, true)
	if code != 0 {
		return code
	}
	plan, err := contract.Plan(cases)
	if err != nil {
		fmt.Fprintf(os.Stderr, "casegen: plan: %v\n", err)
		return 1
	}
	changed, err := contract.Apply(plan, time.Now())
	if err != nil {
		fmt.Fprintf(os.Stderr, "casegen: apply: %v\n", err)
		return 1
	}
	for _, r := range changed {
		fmt.Printf("%-7s %s\n", r.Action, r.Case.TargetPath)
	}
	fmt.Printf("%d created/updated, %d in sync\n",
		len(changed), len(plan)-len(changed))
	return 0
}

func cmdCheck(args []string) int {
	_, cases, code := discover(args, true)
	if code != 0 {
		return code
	}
	plan, err := contract.Plan(cases)
	if err != nil {
		fmt.Fprintf(os.Stderr, "casegen: plan: %v\n", err)
		return 1
	}
	drift := 0
	for _, r := range plan {
		if r.Action != contract.ActionOK {
			fmt.Printf("%-7s %s\n", r.Action, r.Case.TargetPath)
			drift++
		}
	}
	if drift > 0 {
		fmt.Fprintf(os.Stderr, "casegen: %d case(s) out of sync; run `casegen sync`\n", drift)
		return 1
	}
	fmt.Printf("all %d case(s) in sync\n", len(plan))
	return 0
}

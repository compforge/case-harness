# Example: canonical API case

The smallest e2e path is data-driven: a canonical CaseSet contains the request and deterministic assertions; the engine supplies the standard execute/judge lifecycle and writes `verdict.json`.

```bash
export WIDGET_TOKEN=...
e2e run cases.yaml --config config.yaml --runs-dir ./runs
```

For a case that needs resource setup, multiple operations, eventual convergence or expensive teardown, use CaseRun directly as shown in `../python-service` or `../go-service`. Lifecycle code remains outside the CaseSet.

# Example: API mode (pytest + RPCCase + scaffold)

Minimal demo of the "natural-language case → AI-generated pytest → run" flow.

## Layout

```
api-test/
├── config.yaml                  # service base_url + auth headers mapping + discover roots
├── conftest.py                  # env / runner / judge fixtures via e2e_harness.conftest_helpers
├── handlers/
│   └── widget.py                # service-side handler with @case / @spec attached
└── tests/
    └── widget/
        └── test_create_widget__happy.py   # generated test (RPCCase shape)
```

## Workflow

1. **Service owner** writes a handler and stacks `@case` / `@spec`:

   ```python
   # handlers/widget.py
   from e2e_harness.casegen import case, spec

   @spec("Widget creation: tenant_id required; (tenant, name) unique.")
   @case("happy", "minimal create succeeds and returns widget id", group="widget")
   @case("dup_name", "second create with same name returns 409 conflict", group="widget")
   def create_widget(...):
       ...
   ```

   `group` (default `"default"`) decides where the generated test lands —
   `tests/<group>/` — decoupled from the handler's source path. Set it to
   organize, and to disambiguate same-named endpoints across surfaces.

2. **AI agent / developer** runs discover + scaffold to produce starter test files:

   ```python
   from pathlib import Path
   from e2e_harness import (
       DiscoverConfig, discover, render_new, write_new, RPC_CASE_TEMPLATE,
   )

   cases = discover(DiscoverConfig(
       source_root=Path("./handlers"),   # scan dir directly (no source_subdir)
       test_root=Path("./tests"),        # scripts land in tests/<group>/
   ))
   for c in cases:
       write_new(c, RPC_CASE_TEMPLATE)
   ```

3. **Developer / AI** fills the generated test body (`State` fields + `Case.prepare/run/clean`).
   The framework keeps the docstring + meta block + orchestrator regions in sync via
   `update_stale` when the case description changes upstream.

4. **Run**: `pytest tests/ -v` — no extra framework, plain pytest.

See `test_create_widget__happy.py` for what a filled-in test looks like.

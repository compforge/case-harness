# Examples

## api-test (recommended starting point)

Demonstrates canonical CaseSet → data-driven engine → Verdict. See [`api-test/README.md`](api-test/README.md).

## agent-test

Demonstrates the **Eval mode**: dataset-driven RAG / agent evaluation with
EvalEngine, AsyncSSERunner, BasePrepareHandler, and BaseLLMJudge. See
[`agent-test/README.md`](agent-test/README.md).

## go-service

展示 Go CaseRun：显式阶段 budget、类型化 state、独立 cleanup 和 canonical CaseRef。

```bash
cd go-service
export ASANDBOX_BASE_URL=http://localhost:8090
export EXAMPLE_TOKEN=your-token
go test -tags=e2e -v ./...
```

文件：
- `config.yaml` — 服务配置
- `run_test.go` — 聚合本次 `go test` 的 CaseRun 并写 Verdict
- `start_sandbox_e2e_test.go` — HappyPath + Reuse 两个 case

## python-service

展示 Python CaseRun；生命周期语义与 Go 一致，API 使用 dataclass + callable。

```bash
cd python-service
export CONTROL_BASE_URL=http://localhost:8080
export CONTROL_TOKEN=your-token
pytest -v
```

文件：
- `config.yaml` — 服务配置
- `conftest.py` — pytest fixtures（env / runner）
- `test_bot_crud_e2e.py` — prepare/execute/judge/cleanup 完整 case

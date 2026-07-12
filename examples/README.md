# Examples

## api-test (recommended starting point)

Demonstrates the **API mode**: @case/@spec → discover → AI-generated pytest
with RPCCase. See [`api-test/README.md`](api-test/README.md).

## agent-test

Demonstrates the **Eval mode**: dataset-driven RAG / agent evaluation with
EvalEngine, AsyncSSERunner, BasePrepareHandler, and BaseLLMJudge. See
[`agent-test/README.md`](agent-test/README.md).

## go-service

以 sandbox-server (Go) 为例，展示模式 A（代码内联）的写法。

```bash
cd go-service
export ASANDBOX_BASE_URL=http://localhost:8090
export ASANDBOX_TENANT_ID=your-tenant
export ASANDBOX_USER_ID=your-user
go test -tags=e2e -v ./...
```

文件：
- `config.yaml` — 服务配置
- `start_sandbox_e2e_test.go` — HappyPath + Reuse 两个 case

## python-service

以 control-server (Python) 为例，展示两种写法：
- 直接用 `runner` + `judge`（轻量，适合简单 case）
- 用 `BaseCase[State]`（结构化生命周期，适合需要 cleanup 的 case）

```bash
cd python-service
export CONTROL_BASE_URL=http://localhost:8080
export CONTROL_TENANT_ID=your-tenant
export CONTROL_USER_ID=your-user
pytest -v
```

文件：
- `config.yaml` — 服务配置
- `conftest.py` — pytest fixtures（env / runner / judge）
- `test_bot_crud_e2e.py` — CRUD + duplicate 三个 case

# Go SDK

## 项目定位与边界

Python 侧形状的 Go 等价实现，**预先按 e2e/eval/perf 三分**。当前 e2e 落地确定性契约测试、完整 CaseRun 生命周期，以及「case 贴着 handler」的静态覆盖闸门。Python/Go 对齐执行语义与 Verdict，不要求 API 语法一致。

## 代码地图与核心模块

```
go/
├── e2e/                # 确定性契约测试（= python/e2e_harness）
│   ├── caserun/        # prepare/execute/judge/cleanup + phase budgets/evidence + Recorder
│   ├── matrix/         # variant Cartesian product；arm_id/facets 投影
│   ├── core/           # Env / profile+capability / context-aware Poll/Retry/Consistently
│   ├── runner/         # 纯 Runner(ctx) + Outcome / JSONRunner / RawRequest
│   ├── judge/          # 不依赖 testing.T 的 Assertion
│   ├── burst/          # burst.Run[T] 泛型并发发射
│   └── contract/       # +case marker 与 caserun.Ref(caseset,id) 的静态 coverage gate
├── eval/  perf/        # 占位骨架（短期不实现，仅固定包边界与 import 路径）
├── report/             # Go Verdict wire projection
├── cmd/casegen/        # CLI：list / check
└── go.mod              # module: github.com/compforge/case-harness/go
```

## 关键约定

- **case 贴着 handler**：marker grammar 与 plural `specs[]` / `binding.spec_id` 由 spec-case 持有；casegen 用 Go AST 纯静态扫描，不 import、不运行被测服务。
- **执行身份**：测试以字面量 `caserun.Ref("<canonical-caseset>", "<case-id>")` 绑定资产。CaseSet 内 case id 唯一；variant 在同一 CaseRun 内展开，不重复声明 Ref。
- **coverage gate 不生成测试体**：`casegen check` 要求每个 marker 恰有一个 Ref，并拒绝 missing/orphan/duplicate/dynamic ref。测试过程代码归消费方，框架不维护 scaffold/meta 区域。
- **生命周期失败语义**：judge mismatch 用 `caserun.Fail` → fail；请求、环境、timeout、cleanup 异常 → error；cleanup 独立 context 且总执行。
- **单行 marker 天然躲开 gofmt**：每个 `+case` 是一行，没有续行就没有 Go 1.19+ doc-comment 把续行改 tab 缩进的问题。
- **import 路径**：四层在 `e2e/` 下，如 `github.com/compforge/case-harness/go/e2e/core`。

## 开发与测试

```bash
cd go && go test ./...
cd go && go vet ./... && gofmt -l .         # gofmt -l 输出为空才算干净
cd go && go build ./...

# 在被测服务仓库里驱动 casegen（discovery 不依赖被测服务编译）
go run github.com/compforge/case-harness/go/cmd/casegen list  --source ./internal/api
go run github.com/compforge/case-harness/go/cmd/casegen check --source ./internal/api --test ./tests/e2e --caseset sandbox-runtime
```

## References

- 跨语言约定（case/config schema）：[`../spec/conventions.md`](../spec/conventions.md)
- `+case` 注解 fixture：[`e2e/contract/testdata/src/sandbox.go`](e2e/contract/testdata/src/sandbox.go)

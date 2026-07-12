# Go SDK

## 项目定位与边界

Python 侧形状的 Go 等价实现，**预先按 e2e/eval/perf 三分**（对齐 `python/{e2e_harness,eval_harness,perf_harness}`）。当前只有 **e2e** 落地：确定性契约测试 + 「case 贴着 handler」工作流（`+e2e:case` → discover → scaffold）。`eval`/`perf`/`report` 为占位骨架，等 Python 形状稳定后回填。三个测试 SDK 互不 import（先复制后收敛），唯一共享 `report`。

## 代码地图与核心模块

```
go/
├── e2e/                # 确定性契约测试（= python/e2e_harness）
│   ├── core/           # LoadEnv+YAML插值 / profile+capability gating(/healthz) / UniqueID(For) / Ptr / Cleanup / PollUntil / Retry
│   ├── runner/         # Runner + Outcome(+Decode) + dot-path / JSONRunner / RawRequest（负向测试裸 body）
│   ├── judge/          # Assert + 内置 Assertion 集
│   ├── burst/          # burst.Run[T] 泛型并发发射
│   └── contract/       # +e2e:case/+e2e:spec → Discover(go/ast) → Scaffold(*_e2e_test.go) + meta block / case_hash 漂移检测
├── eval/  perf/        # 占位骨架（短期不实现，仅固定包边界与 import 路径）
├── report/             # 占位骨架：中立报告 IR（eval/perf 共享，= python/report_kit）
├── cmd/casegen/        # CLI：list / sync / check
└── go.mod              # module: github.com/qiankunli/case-harness/go
```

## 关键约定

- **case 贴着 handler**：在**被测服务仓库**的 handler 上写 `+e2e:case`/`+e2e:spec` 注释（借 kubebuilder 的 `+` 约定 + 单行 `key=val` 形态；NL 字段 `input/expect/forbid` 用反引号包住，内嵌逗号/分号不受影响）。`casegen` 用 `go/ast` 纯静态扫描发现，**不 import、不运行**被测服务——注释对构建零成本，handler 编不过也能扫。
- **框架托管区 vs 人写区**：生成的 `*_e2e_test.go` 里，`package` 之上的 doc 块 + meta 块由框架重写；`package` 及以下（imports + 测试体）归人/AI，`sync` 原样保留。`case_hash` 变了 → 插 `STALE` 标记、刷新 doc/meta、保留 body。
- **单行 marker 天然躲开 gofmt**：每个 `+e2e:case` 是一行，没有续行就没有 Go 1.19+ doc-comment 把续行改 tab 缩进的问题（手写解析 ~40 行，不引 controller-tools）。
- **import 路径**：四层在 `e2e/` 下，如 `github.com/qiankunli/case-harness/go/e2e/core`。

## 开发与测试

```bash
cd go && go test ./...
cd go && go vet ./... && gofmt -l .         # gofmt -l 输出为空才算干净
cd go && go build -tags e2e ./...           # 验证带 e2e tag 的生成测试可编译

# 在被测服务仓库里驱动 casegen（discovery 不依赖被测服务编译）
go run github.com/qiankunli/case-harness/go/cmd/casegen list  --source ./internal/api
go run github.com/qiankunli/case-harness/go/cmd/casegen sync  --source ./internal/api --test ./tests/e2e
go run github.com/qiankunli/case-harness/go/cmd/casegen check --source ./internal/api --test ./tests/e2e   # CI gate
```

## References

- 跨语言约定（case/config schema）：[`../spec/conventions.md`](../spec/conventions.md)
- `+e2e:case` 注解 fixture：[`e2e/contract/testdata/src/sandbox.go`](e2e/contract/testdata/src/sandbox.go)

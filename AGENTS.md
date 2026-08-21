# case-harness

## 项目定位与边界

**初衷**：一个 AI 项目会越来越复杂——功能多、链路长、测试面广，经常临到发版才发现问题，慌慌张张地修，修完也不敢说系统就完全没问题。本仓库的回答是：把"系统健壮不健壮"拆成几个可以分开回答的问题，各建一类 harness——前三类是**黑盒测试**（发请求看响应），trace 与 trajectory 是两种**开盒分析**（分别看物理链路与 agent 行动过程）——

| 问题 | 类型 | SDK |
|------|----------|-----|
| 接口对不对 | API 测试（e2e，黑盒） | `python/e2e_harness` / `go/e2e` |
| agent 效果好不好 | 效果测试（eval，黑盒） | `python/eval_harness` |
| 压力下表现如何 | 压力测试（perf，黑盒） | `python/perf_harness` / `typescript/perf-harness` |
| 链路内部哪层先反常 | trace 分析（trace，开盒） | `python/trace_harness` / `typescript/trace-harness` |
| agent 的行动过程是否合理 | 轨迹评估（trajectory，开盒） | `python/trajectory_harness` |

**边界**：跨语言（Go + Python + TypeScript）测试框架聚合仓库，各语言目录是独立工程。框架不 import 被测服务的 internal 代码，纯黑盒（HTTP / SSE / DB-query 由服务侧自己包装）。

核心模型、长期功能测试边界、资产到 Verdict 的主流程与 owner 分工统一见 [`docs/kernel.md`](docs/kernel.md)。当前已实现 Case 路径；Playbook → Script → Web / Android / iOS / 产品 API Target 是长期边界，尚未实现。

## 代码地图与核心模块

各子模块的定位、代码地图、关键约定收敛在**各自的 AGENTS.md**，本文件不再展开；改某个 SDK 前先读它的 AGENTS.md。

```
case-harness/
├── spec/                # 运行时约定层：case 兼容投影 / config / verdict / conventions
├── conformance/         # 跨语言共享行为 fixture
├── python/              # Python 工程（uv），五个 sibling SDK + 共享 common
│   ├── e2e_harness/     # API 测试（e2e）：确定性契约测试，pytest 驱动      → 见其 AGENTS.md
│   ├── eval_harness/    # 效果测试（eval）：非确定性质量评测，大表 + reconciler → 见其 AGENTS.md
│   ├── perf_harness/    # 压力测试（perf）：资源约束下的容量/资源画像        → 见其 AGENTS.md
│   ├── trace_harness/   # trace 分析（trace）：开盒 OTel/Jaeger span 归因，调用栈+判读+corpus → 见其 AGENTS.md
│   ├── trajectory_harness/ # 轨迹评估：外部记录→Trajectory→Evaluator → 见其 AGENTS.md
│   ├── common/          # 中立共享层：case / verdict / llm / facets + report_kit（报告 IR + HTML 渲染），五个 SDK 共用、无业务概念
│   └── …/tests/         # 测试在各自包内（e2e_harness/tests 等；common 同），打包时排除
├── go/                  # Go SDK（参考实现，形状对齐 spec）→ 见 go/AGENTS.md
├── typescript/          # TypeScript SDK；perf/trace 实现共同遵守 spec 下的跨语言契约
├── examples/            # 接入示例：api-test / agent-test
└── docs/                # 跨 SDK 设计文档
```

## 关键约定

- **md 文档分工**：`AGENTS.md` 给 developer 看（代码地图、约定、扩展点），`README.md` 给 user 看（怎么接入、怎么跑）。两者会共用一部分项目定位/边界的内容，但侧重点不同——允许适度重复，不允许混淆受众。
- **资产与执行分工遵循 Kernel**：Case / Playbook 等稳定资产格式只有一个 canonical owner；case-harness 负责编译、Runner / Driver、Judge、Run 产物与 Verdict。具体约束见 [`docs/kernel.md`](docs/kernel.md)。
- **同一 CaseSet，多种执行视角**：Eval / Perf 直接消费 spec-case CaseSet；Experiment 只能选择 Case、设置 weight 或其它运行参数，不能复制或覆盖资产字段。跨语言约束由 `conformance/case/` 证明。
- **可验证交付从开发期开始**：被测项目随需求、外部行为变更和缺陷修复维护 Spec / Case，再由 case-harness 在部署后针对指定版本与环境执行为 Verdict。项目拥有验证资产与判定标准，部署领域拥有环境、凭据、触发和发布策略；API、CLI、Pipeline、Job 只是可替换适配。
- 五个 Python SDK 共享同一个 uv 工程与 `spec/` 约定，**互不 import**；公共能力集中在 `common`（case / verdict / llm / facets + report_kit 报告 IR）这一中立共享层，而不是 SDK 之间互相复用。各 SDK 仍自带一小撮协议原语（Outcome 形状、runner、SSEParser；perf 自带 httpx 发压栈、trace 自带薄 driver）——**先复制后收敛**，确属公共再收进 `common`。trace 的 parquet 持久化走可选 extra `[trace-corpus]`，不给其它 SDK 增重。
- 新增能力先想清楚归哪类问题（对错 / 效果 / 容量 / 归因），落到对应 SDK；跨 SDK 的"公共抽象"冲动默认抑制，先复制后收敛，确属公共再进 `common`。
- Go/Python e2e 共享 CaseRun 语义（prepare/execute/judge/cleanup、阶段 budget、Verdict），API 保持各自语言习惯；资产模型仍统一由 spec-case 持有。
- Go/Python e2e 的共同语义由 `conformance/e2e/` fixture 约束；Go 项目通过 `e2e/testrun.Run` 将一次 `go test` 中的 CaseRun 聚合到统一 run 目录，不在消费仓重复实现 Recorder/TestMain/Verdict 胶水。它是 Go testing adapter，不引入跨语言 Suite 概念。
- Trace Harness 的 canonical 定义是 [`spec/trace-harness.md`](spec/trace-harness.md) 与
  `schema/trace/v1/`；Python 和 TypeScript 是对等实现，共用 `conformance/trace/`
  fixtures。通用包不承载业务域知识，业务能力通过 scoped
  `TraceContributions` 显式组合。

## 开发与测试

```bash
# 测试在各 SDK 包内（<pkg>/tests/），共用 uv 工程；pytest 无参=全量（testpaths）
cd python && uv sync && uv run pytest -q
cd python && uv run pytest perf_harness/tests/ -q   # 只跑某个 SDK
cd python && make lint        # ruff
cd python && make bump        # patch 版本号 + uv lock（case-harness 发布用）

# eval_harness 端到端（mock，无需 live server）
cd python && uv run python -m eval_harness.cli eval_harness/materials/experiments/smoke.yaml --mock --fresh --runs-dir /tmp/eh

# perf_harness 端到端（mock，无需 live server / 集群）
cd python && uv run python -m perf_harness.cli run perf_harness/examples/mock.yaml --out /tmp/ph

# trace_harness 端到端（离线 jaeger 文件 → 调用栈 + 判读；批量 corpus 用 trace batch <exp.yaml>）
cd python && uv run trace single ../conformance/trace/fixtures/genai-basic.jsonl --diagnose

# Go（参考实现）
cd go && go test ./...

# TypeScript trace-harness
cd typescript/trace-harness && bun install --frozen-lockfile && bun test && bun run typecheck

# TypeScript perf-harness
cd ../perf-harness && bun install --frozen-lockfile && bun test && bun run typecheck
```

## References

- 暂缓能力与启动条件：[`docs/backlog.md`](docs/backlog.md)
- 内核模型、测试边界与长期功能测试：[`docs/kernel.md`](docs/kernel.md)
- Quality Harness 的定位、发现式评估与异步触发模型：[`docs/quality-harness.md`](docs/quality-harness.md)
- e2e_harness（API 测试）：[`python/e2e_harness/AGENTS.md`](python/e2e_harness/AGENTS.md)
- eval_harness（效果测试）：[`python/eval_harness/AGENTS.md`](python/eval_harness/AGENTS.md)，使用指南 [`python/eval_harness/README.md`](python/eval_harness/README.md)
- perf_harness（压力测试）：[`python/perf_harness/AGENTS.md`](python/perf_harness/AGENTS.md)，使用指南 [`python/perf_harness/README.md`](python/perf_harness/README.md)
- Perf 跨语言契约：[`spec/perf-contract.md`](spec/perf-contract.md) + [`spec/perf-run-schema.yaml`](spec/perf-run-schema.yaml) + [`spec/perf-outcome-schema.yaml`](spec/perf-outcome-schema.yaml)
- TypeScript perf-harness：[`typescript/perf-harness/AGENTS.md`](typescript/perf-harness/AGENTS.md)，使用指南 [`typescript/perf-harness/README.md`](typescript/perf-harness/README.md)
- trace_harness（trace 分析）：[`python/trace_harness/AGENTS.md`](python/trace_harness/AGENTS.md)，设计文档 [`docs/trace-harness.md`](docs/trace-harness.md)
- trajectory_harness（agent 轨迹评估）：[`python/trajectory_harness/AGENTS.md`](python/trajectory_harness/AGENTS.md)，设计文档 [`docs/trajectory-harness.md`](docs/trajectory-harness.md)
- Go SDK：[`go/AGENTS.md`](go/AGENTS.md)
- TypeScript trace-harness：[`typescript/trace-harness/AGENTS.md`](typescript/trace-harness/AGENTS.md)，使用指南 [`typescript/trace-harness/README.md`](typescript/trace-harness/README.md)
- 顶层导览：[`README.md`](README.md)
- 跨语言约定：[`spec/conventions.md`](spec/conventions.md)
- 统一判定出口（run 目录 + verdict.json，四家共用，devloop 消费）：[`spec/verdict-schema.yaml`](spec/verdict-schema.yaml) + conventions.md「Run 产物与 verdict 出口」
- 接入示例：[`examples/api-test/`](examples/api-test/) / [`examples/agent-test/`](examples/agent-test/)

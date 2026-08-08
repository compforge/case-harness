# case-harness

> **Cases in, verdicts out.** 一组跨语言测试 harness，把"系统健壮不健壮"拆成若干可分开回答的问题——接口对错（e2e）、agent 效果（eval）、压力容量（perf）、链路归因（trace）与 agent 行动轨迹——共用同一份可积累的 **case** 资产。与 [spec-case](https://github.com/compforge/spec-case)（资产格式）、[case-code-review](https://github.com/compforge/case-code-review)（白盒消费方）互为姊妹仓。｜ English: [README.md](./README.md)

## 为什么有这个仓库

一个 AI 项目会越来越复杂——功能多、链路长、测试面广，经常临到发版才发现问题，慌慌张张地修，修完也不敢说系统就完全没问题。本仓库的回答是：把"系统健壮不健壮"拆成几个可以分开回答的问题，各建一类 harness——前三类是**黑盒测试**（发请求看响应），trace 与 trajectory 是互补的**开盒分析**：

| 问题 | 类型 | SDK |
|------|------|-----|
| 接口对不对 | API 测试（e2e，黑盒） | `python/e2e_harness` |
| agent 效果好不好 | 效果测试（eval，黑盒） | `python/eval_harness` |
| 压力下表现如何 | 压力测试（perf，黑盒） | `python/perf_harness` |
| 链路内部哪层先反常 | trace 分析（trace，开盒） | `python/trace_harness` / `typescript/trace-harness` |
| agent 的决策和行动是否合理 | 轨迹评估（trajectory，开盒） | `python/trajectory_harness` |

提供 SDK，不提供测试本身：被测服务（SUT）在自己仓库里以 SDK 形式接入，按自己的协议/认证/资源生命周期组织。

## 核心思想

1. **不同判定实现思路迥异，但 case 应该一致**。case 只描述"如何给系统发请求"，不绑定怎么判定；同一份 case，e2e 拿去看对错，eval 拿去看效果，perf 拿去看压力下的表现。canonical 资产格式与模型由 `spec-case` 持有，本仓 `spec/` 只保留运行时约定与兼容投影。
2. **case 是可积累的资产**。case 与判定解耦后就能持续积累；case 攒得越多，发版前全量跑一遍，就越有底气相信系统没问题。
3. **实验词汇统一为 Experiment → Arm → Trial**。Experiment 回答一个问题，Arm 是参与比较的命名配置，Trial 是某个 Arm 的一次真实执行。结果落在 `runs/<scope>/<run-id>/`，`arm_id` 作为显式对齐键贯穿产物。
4. **一次执行，多面观测**。同一次请求可同时服务对错（e2e）、效果（eval）、延迟/资源（perf）、链路归因（trace）和行动轨迹（trajectory）——这些 harness 是不同视角，不是多次独立发压。

统一的输出是 `verdict.json`（schema 见 [`spec/verdict-schema.yaml`](spec/verdict-schema.yaml)）：人读它，CI 读它，agent 开发循环也读它自纠偏。

## 与 spec-case 的分工

[spec-case](https://github.com/compforge/spec-case) 是**资产层**：`@spec`/`@case`/`@rule` 标注长在代码上，经工具链蒸馏成机器可读资产，靠 symbol-id 与代码稳定绑定；canonical `Case` 模型也由它提供（`spec_case.model`）。case-harness 是**运行层**：黑盒地把这些 case 跑成 verdict。同一份资产的白盒消费方是 [case-code-review](https://github.com/compforge/case-code-review)（把 spec/case 附到评审 unit 上作 checklist）。

## Layout

```
case-harness/
├── spec/                # 运行时约定层：case 兼容投影 / verdict / config
├── python/              # Python 工程（uv），五个 sibling SDK + 共享 harness_common
│   ├── e2e_harness/     # API 测试：确定性契约测试，判定即数据，pytest 驱动
│   ├── eval_harness/    # 效果测试：Experiment/Arm 对照 + Worksheet 大表 + reconciler
│   ├── perf_harness/    # 压力测试：资源约束下的容量/资源画像
│   ├── trace_harness/   # trace 分析：OTel/Jaeger span 归因，调用栈 + 判读 + corpus
│   ├── trajectory_harness/ # agent 轨迹归一与评估
│   └── harness_common/  # 中立共享层：verdict / llm / report_kit
├── go/                  # Go SDK（参考实现，形状对齐 spec/）
├── typescript/          # TypeScript SDK；trace-harness 对齐 Python 分析 IR
├── examples/            # 接入示例：api-test / agent-test
└── docs/                # 跨 SDK 设计文档
```

五个 Python SDK 共享同一 uv 工程与 `spec/` 约定，但**互不 import**；公共能力集中在 `harness_common` 这一中立共享层。

## Quickstart

```bash
# Python：五个 SDK 共用一个 uv 工程
cd python && uv sync && uv run pytest -q

# eval_harness 端到端（mock，无需 live 服务）
uv run python -m eval_harness.cli eval_harness/materials/experiments/smoke.yaml --mock --fresh --runs-dir /tmp/ch

# perf_harness 端到端（mock）
uv run python -m perf_harness.cli run perf_harness/examples/mock.yaml --out /tmp/ph

# trace 分析（离线 jaeger 文件 → 调用栈 + 判读）
uv run trace single ../conformance/trace/fixtures/genai-basic.jsonl --diagnose

# Go（参考实现）
cd go && go test ./...

# TypeScript trace-harness
cd typescript/trace-harness && bun install --frozen-lockfile && bun test
```

各 SDK 的接入方式见其目录下的 `README.md`；开发者向的代码地图与约定见各 `AGENTS.md`。

## Status

Early public release。canonical case schema 来自 `spec-case`；本仓 `spec/` 下的 verdict 与运行时约定是稳定中心。SDK API 仍可能调整。Go SDK 按批次跟进 Python 侧，TypeScript trace-harness 的公开分析 IR 与 Python 保持对齐。

# case-harness

## 项目定位与边界

**初衷**：一个 AI 项目会越来越复杂——功能多、链路长、测试面广，经常临到发版才发现问题，慌慌张张地修，修完也不敢说系统就完全没问题。本仓库的回答是：把"系统健壮不健壮"拆成几个可以分开回答的问题，各建一类 harness——前三类是**黑盒测试**（发请求看响应），trace 与 trajectory 是两种**开盒分析**（分别看物理链路与 agent 行动过程）——

| 问题 | 类型 | SDK |
|------|----------|-----|
| 接口对不对 | API 测试（e2e，黑盒） | `python/e2e_harness` |
| agent 效果好不好 | 效果测试（eval，黑盒） | `python/eval_harness` |
| 压力下表现如何 | 压力测试（perf，黑盒） | `python/perf_harness` |
| 链路内部哪层先反常 | trace 分析（trace，开盒） | `python/trace_harness` / `typescript/trace-harness` |
| agent 的行动过程是否合理 | 轨迹评估（trajectory，开盒） | `python/trajectory_harness` |

**核心思想（后续演进的指导原则）**：

1. **三类测试实现思路迥异，但 case 应该是一致的**。case 只描述"如何给系统发请求"，不绑定怎么判定；同一份 case，e2e 拿去看对错，eval 拿去看 agent 效果，perf 拿去看压力下的表现。canonical Case/CaseSet 格式与模型由 [`spec-case`](https://github.com/compforge/spec-case) 持有；本仓 [`spec/case-schema.yaml`](spec/case-schema.yaml) 只是运行时兼容投影，harness 约定见 [`spec/conventions.md`](spec/conventions.md)「Case 规范」。
2. **case 是可积累的资产**。case 与判定解耦后就能持续积累；case 攒得越多，发版前全量跑一遍没问题，就越有底气相对地相信系统没问题——把"慌张修完不敢保证"换成"跑完一遍心里有数"。
3. **实验词汇统一为 Experiment → Arm → Trial**。Experiment 回答一个问题，Arm 是参与比较的命名配置，Trial 是某 Arm 的一次真实执行；各 harness 保留强类型的本地 Arm，不抽一个 `dict` 配置的通用基类。产物按 run 落盘，记录与渲染分离。
4. **一次执行，多面观测**。case 统一之后，跑一遍 case 不必只服务一类测试：同一次请求的产出，可以同时服务对错（e2e）、效果（eval）、延迟/资源（perf）、链路内部归因（trace）和行动轨迹（trajectory）——这些 harness 是不同视角，而不是多次独立发压。

**边界**：跨语言（Go + Python + TypeScript）测试框架聚合仓库，各语言目录是独立工程。框架不 import 被测服务的 internal 代码，纯黑盒（HTTP / SSE / DB-query 由服务侧自己包装）。

## 愿景

两条长期线，决定 `spec/` 与 `common` 的演进优先级：

1. **融入 devloop——成为 agent 开发循环的判定基础设施**。各 harness 统一从 `runs/<scope>/<run-id>/verdict.json` 出判定（schema 见 [`spec/verdict-schema.yaml`](spec/verdict-schema.yaml)），devloop 等开发循环"读 verdict 自纠偏"：改完代码跑 case → 读 verdict 定位挂点 → 再改再跑。harness 的角色因此不止"人跑的测试工具"，而是 agent 开发循环里的反馈节点。
2. **跑 case（driver）→ 汇总产出 → 数据挖掘**。一个执行波次（如 100 个 case 主动驱动 / 跑一夜）落下四个数据平面：verdict（对错）/ metrics（延迟资源）/ traces（链路）/ findings（判读）。单平面的数字不可行动；按对齐键 join 后跑**模式注册表**才出可行动假设（"fail 的 23 个 case 里 18 个命中 tool_churn → 改该 tool 的 desc"），再用 eval A/B 验证改进——详见 [`docs/trace-harness.md`](docs/trace-harness.md) §3.7。

两条线押在同一处地基上：**case（输入）与 verdict（输出）的统一**。`case_id` / `arm_id` / `trace_id` / `runs/<scope>/<run-id>` 布局是跨平面 join 键——**各 harness 迭代时必须守住对齐键**（约定见 [`spec/conventions.md`](spec/conventions.md)「对齐键」）；破坏对齐键 = 同时砍断 devloop 消费与数据挖掘。

## 代码地图与核心模块

各子模块的定位、代码地图、关键约定收敛在**各自的 AGENTS.md**，本文件不再展开；改某个 SDK 前先读它的 AGENTS.md。

```
case-harness/
├── spec/                # 运行时约定层：case 兼容投影 / config / verdict / conventions
├── python/              # Python 工程（uv），五个 sibling SDK + 共享 common
│   ├── e2e_harness/     # API 测试（e2e）：确定性契约测试，pytest 驱动      → 见其 AGENTS.md
│   ├── eval_harness/    # 效果测试（eval）：非确定性质量评测，大表 + reconciler → 见其 AGENTS.md
│   ├── perf_harness/    # 压力测试（perf）：资源约束下的容量/资源画像        → 见其 AGENTS.md
│   ├── trace_harness/   # trace 分析（trace）：开盒 OTel/Jaeger span 归因，调用栈+判读+corpus → 见其 AGENTS.md
│   ├── trajectory_harness/ # 轨迹评估：外部记录→Trajectory→Evaluator → 见其 AGENTS.md
│   ├── common/          # 中立共享层：case / verdict / llm / facets + report_kit（报告 IR + HTML 渲染），五个 SDK 共用、无业务概念
│   └── …/tests/         # 测试在各自包内（e2e_harness/tests 等；common 同），打包时排除
├── go/                  # Go SDK（参考实现，形状对齐 spec）→ 见 go/AGENTS.md
├── typescript/          # TypeScript SDK；trace-harness 对齐 Python 分析 IR 与交互 HTML
├── examples/            # 接入示例：api-test / agent-test
└── docs/                # 跨 SDK 设计文档
```

## 关键约定

- **md 文档分工**：`AGENTS.md` 给 developer 看（代码地图、约定、扩展点），`README.md` 给 user 看（怎么接入、怎么跑）。两者会共用一部分项目定位/边界的内容，但侧重点不同——允许适度重复，不允许混淆受众。
- **case 资产只有一个 owner**：共享字段与模型先在 `spec-case` 演进；`spec/case-schema.yaml` 只保留当前 harness 的兼容投影和运行时扩展，不得独立定义第二套 canonical case。
- 五个 Python SDK 共享同一个 uv 工程与 `spec/` 约定，**互不 import**；公共能力集中在 `common`（case / verdict / llm / facets + report_kit 报告 IR）这一中立共享层，而不是 SDK 之间互相复用。各 SDK 仍自带一小撮协议原语（Outcome 形状、runner、SSEParser；perf 自带 httpx 发压栈、trace 自带薄 driver）——**先复制后收敛**，确属公共再收进 `common`。trace 的 parquet 持久化走可选 extra `[trace-corpus]`，不给其它 SDK 增重。
- 新增能力先想清楚归哪类问题（对错 / 效果 / 容量 / 归因），落到对应 SDK；跨 SDK 的"公共抽象"冲动默认抑制，先复制后收敛，确属公共再进 `common`。
- Go SDK 短期不跟进 Python 侧新增，等形状稳定后批量同步。
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
```

## References

- e2e_harness（API 测试）：[`python/e2e_harness/AGENTS.md`](python/e2e_harness/AGENTS.md)
- eval_harness（效果测试）：[`python/eval_harness/AGENTS.md`](python/eval_harness/AGENTS.md)，使用指南 [`python/eval_harness/README.md`](python/eval_harness/README.md)
- perf_harness（压力测试）：[`python/perf_harness/AGENTS.md`](python/perf_harness/AGENTS.md)，使用指南 [`python/perf_harness/README.md`](python/perf_harness/README.md)
- trace_harness（trace 分析）：[`python/trace_harness/AGENTS.md`](python/trace_harness/AGENTS.md)，设计文档 [`docs/trace-harness.md`](docs/trace-harness.md)
- trajectory_harness（agent 轨迹评估）：[`python/trajectory_harness/AGENTS.md`](python/trajectory_harness/AGENTS.md)，设计文档 [`docs/trajectory-harness.md`](docs/trajectory-harness.md)
- Go SDK：[`go/AGENTS.md`](go/AGENTS.md)
- TypeScript trace-harness：[`typescript/trace-harness/AGENTS.md`](typescript/trace-harness/AGENTS.md)，使用指南 [`typescript/trace-harness/README.md`](typescript/trace-harness/README.md)
- 顶层导览：[`README.md`](README.md)
- 跨语言约定：[`spec/conventions.md`](spec/conventions.md)
- 统一判定出口（run 目录 + verdict.json，四家共用，devloop 消费）：[`spec/verdict-schema.yaml`](spec/verdict-schema.yaml) + conventions.md「Run 产物与 verdict 出口」
- 接入示例：[`examples/api-test/`](examples/api-test/) / [`examples/agent-test/`](examples/agent-test/)

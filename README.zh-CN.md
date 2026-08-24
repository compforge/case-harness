# case-harness

> **Cases in, verdicts out.** 输入可复用 Case，由 e2e、eval、perf、trace 和 trajectory 运行生成统一、机器可读的 Verdict。English: [README.md](./README.md)。

## 这是什么

case-harness 是一组跨语言测试 SDK，用于回答已经无法由一条测试命令概括的项目质量问题。它把 API 对错、Agent 效果、系统容量、链路归因和 Agent 行动轨迹拆成不同判定视角，同时让它们复用同一份版本化 Case 资产。

本仓库提供 Harness SDK 和平台工具，不提供某个产品的现成测试。被测项目继续拥有自己的 Case、协议适配、凭据、资源生命周期和验收标准。

## 可以评估什么

| 问题 | 视角 | 已有 SDK |
|---|---|---|
| 公开 API 是否仍按契约工作？ | e2e | Python / Go |
| Agent 产出质量是否达标？ | eval | Python |
| 在声明的负载和资源约束下表现如何？ | perf | Python / TypeScript |
| 物理调用链中哪一层最先异常？ | trace | Python / TypeScript |
| Agent 的决策和行动过程是否合理？ | trajectory | Python |

前三个视角根据系统公开行为进行判定；trace 和 trajectory 检查执行证据。“黑盒”描述的是判定边界，而不是要求所有准备动作都只能调用公开 API：准备环境、注入受控故障或观察资源压力，仍可能需要部署级工具。

当前 e2e 以单个服务的公开边界为目标。产品级 Web、移动端和跨服务功能测试属于长期范围，不与服务 API 契约测试混为一谈。

## 如何工作

```text
项目拥有的 canonical CaseSet
    + 环境与执行代码
    → CaseRun → Observation
    → Unit → 版本化 Dataset

Dataset + Evaluators / Measurers / optional Policy
    → EvaluationRun → Worksheet
    → JSON / verdict.json / HTML report
```

| 概念 | 含义 |
|---|---|
| **Case** | 由 `case_id` 标识的稳定、可复用测试输入与判定数据；canonical 格式由 [spec-case](https://github.com/compforge/spec-case) 持有。 |
| **Observation** | Case 执行后实际发生的事实，例如 outcome、response、性能采样、trace 或 trajectory，并保留来源身份。 |
| **Unit** | Harness 声明的评估单元，数据来源是 Case 与一个或多个 Observation；Worksheet 一行一个 Unit。 |
| **Dataset** | 可复用、版本化的 Unit facts 集合，不包含某次具体评估运行的结果。 |
| **Worksheet** | 一次 EvaluationRun 基于 Dataset 的行式结果，为每个 Unit 追加 Evaluation 与 Measurement cell。 |
| **CaseRun** | 一个 Case 在一个环境和 variant 上的真实执行，具有显式阶段预算与 cleanup 语义。 |
| **Run** | 一次真实执行的生命周期和产物边界，携带环境与对齐身份。 |
| **Report** | Worksheet 面向机器的 JSON 或面向人的 HTML 投影。 |
| **Verdict** | 人、CI 和 Agent 开发闭环共同消费的机器可读结论。 |

同一 Case 可以从多个角度观察。一次执行已经产生 response、性能采样、trace 或 trajectory 时，应将这些 Observation 固定为可复用 Dataset；选择不同 Judge、Measurer 或 Policy 即可生成新的 Worksheet 和报告，不重复执行系统。

## 共享平台工具箱

部分执行机制会服务多个 Harness。例如，恢复 E2E 和性能测试都需要可靠地发现 Kubernetes 工作负载、等待状态收敛并采集 Event 证据。Go `kube` 包统一提供 namespace-scoped 的 Kubernetes 控制与观测，但不拥有任何业务 Case、负载模型或 Verdict。

消费项目仍负责选择目标工作负载、决定何时允许注入故障，以及什么结果足以证明恢复或性能达标。其它故障注入后端可以继续加入工具箱，而不把实验意图从项目中搬走。

## 快速开始

先选择最接近自身场景的示例：

| 示例 | 适用场景 |
|---|---|
| [`examples/api-test`](examples/api-test/README.md) | 小型、数据驱动的 API Case |
| [`examples/python-service`](examples/python-service/) | 带准备和清理的 Python CaseRun |
| [`examples/go-service`](examples/go-service/) | Go CaseRun、`go test` 聚合与 Verdict 输出 |
| [`examples/agent-test`](examples/agent-test/README.md) | 数据集驱动的 Agent 评测 |

在源码目录运行 Python API 示例：

```bash
cd python
uv sync
export WIDGET_TOKEN=...
uv run e2e run ../examples/api-test/cases.yaml \
  --config ../examples/api-test/config.yaml \
  --runs-dir ../runs
```

针对一个已部署服务运行 Go 示例：

```bash
cd examples/go-service
export ASANDBOX_BASE_URL=http://localhost:8090
export EXAMPLE_TOKEN=...
go test -tags=e2e -v ./...
```

两条路径都会生成以 `verdict.json` 结尾的 Run 目录。被跳过或执行出错的 Case 会明确保留，不能被解释为已经验证成功。

## Owner 分工

| Owner | 职责 |
|---|---|
| 被测项目 | 版本化 Case 资产、测试代码、业务动作、验收标准 |
| case-harness | Case 执行、Runner / Driver、Judge、Run 产物、Verdict 投影、共享平台工具 |
| spec-case | canonical Case 模型与代码到 Case 的意图标记 |
| 部署工作流 | 环境、凭据、目标 revision、触发策略与发布门禁 |

这个分工让测试意图贴近产品，同时允许执行机制和输出契约集中演进。[case-code-review](https://github.com/compforge/case-code-review) 从白盒评审视角消费同一份资产。

## SDK 地图

| 路径 | 能力 |
|---|---|
| `python/e2e_harness` / `go/e2e` | 确定性 CaseRun 执行与 API 断言 |
| `python/eval_harness` | Agent 评测与对照实验 |
| `python/perf_harness` / `typescript/perf-harness` | 发压、SLO 与容量证据 |
| `python/trace_harness` / `typescript/trace-harness` | Trace 归一、归因与 Finding |
| `python/trajectory_harness` | Agent 轨迹归一与评估 |
| `go/kube` | e2e / perf 共用的 Kubernetes 控制与观测 |

## 仓库开发

```bash
cd python && uv sync && uv run pytest -q
cd ../go && go test ./...
cd ../typescript/trace-harness && bun install --frozen-lockfile && bun test
cd ../perf-harness && bun install --frozen-lockfile && bun test
```

## 状态

case-harness 仍处于早期公开阶段。canonical Case schema 来自 spec-case；`spec/` 下的 Verdict 与运行时契约是本仓库的稳定中心。不同语言 SDK 可以覆盖不同能力，但应持续遵守同一组契约。

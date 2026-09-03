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
    + 执行 / 采集
    → Observation
    → Unit（Case + Observation + Annotation）
    → 版本化 Dataset

Dataset + Detectors / Evaluators / Measurers / optional Policy
    → EvaluationRun
        detect   → Finding
        evaluate → Evaluation
        measure  → Measurement
    → Worksheet（Unit + Finding + Evaluation + Measurement）
    → Metric / Verdict / Report（JSON / HTML）

Experiment
    → ExperimentRun
        → Execution × N（例如 E2E CaseRun / perf Trial）
            → OperationRun × N
                → Outcome
    → Reducer.reduce（只读已记录事实）
    → Artifact × N
        → Verdict
        → Report
```

| 概念 | 含义 |
|---|---|
| **Forge** | 托管代码 Repository 的系统，例如 GitHub、GitLab 或企业内部代码平台。 |
| **Repository** | 由 Forge 和路径共同标识的代码仓；一个 Repository 可以包含多个 Component。 |
| **Product** | 由多个 Component 组成的业务产品；Product 与 Component 的多对多关系由 registry 维护。 |
| **Component** | Repository 中可独立构建或发布的稳定组件；不产生运行 workload 的 Component 可以没有 Service。 |
| **Environment** | 标识运行证据产生位置的具名部署和运行环境。 |
| **Service** | Component 在某个 Environment 中具名的运行体现。 |
| **Operation** | Service 对外提供的一项具名能力。 |
| **HttpOperation** | 通过 HTTP method 和 path 暴露的 Operation；base URL 仍属于 Service。 |
| **Deployment** | 把 Component 发布到 Environment、从而创建或更新 Service 的一次部署记录。 |
| **Deployer** | 由 Helm、Docker 等具体机制实现的部署端口。 |
| **Experiment** | 一份具名、可复现的验证意图；各 Harness 子类增加自己的 Case、Arm、Workload、Metric 或 Policy。 |
| **ExperimentRun** | Experiment 的一次真实执行，以 `run_id` 和创建时间标识；领域模型可以简称为 `Run`。 |
| **Execution** | ExperimentRun 内由领域定义的一组工作；E2E 将其具体化为 CaseRun，perf 将其具体化为 Trial。 |
| **OperationRun** | 对某个 Service 的 Operation 的一次执行，拥有该次调用产生的原始 Outcome。 |
| **Outcome** | OperationRun 产生的原始领域证据；HTTP、SSE、perf 等协议字段留在领域子类。 |
| **Reducer** | 把 ExperimentRun 中已记录事实投影为 Artifact 的领域组件；不得再次调用被测 Service。 |
| **Artifact** | ExperimentRun 的具名、可持久化产物；具体内容和 schema 归领域所有，公共层只记录逻辑名称与相对路径。 |
| **Case** | 由 `case_id` 标识的稳定、可复用测试输入与判定数据；canonical 格式由 [spec-case](https://github.com/compforge/spec-case) 持有。 |
| **Observation** | Case 执行后实际发生的事实，例如 outcome、response、性能采样、trace 或 trajectory，并保留来源身份。 |
| **Unit** | Harness 声明的评估单元，数据来源是 Case 与一个或多个 Observation；Worksheet 一行一个 Unit。 |
| **Annotation** | 当前评估前已经存在的人工、外部系统或模型监督信息，例如 label、reference 和复核结论。 |
| **Dataset** | 可复用、版本化的 Unit facts 与已有 Annotation 集合，不包含某次具体 EvaluationRun 的结果。 |
| **EvaluationRun** | 对一个固定 Dataset version 执行一组 Detector、Evaluator、Measurer 与可选 Policy 的运行实例。 |
| **Finding** | `detect` 返回的模式或异常，带有证据和原因假设，但不携带质量 verdict。 |
| **Evaluation** | Judge 或 Evaluator 根据契约对 Unit 作出的质量判断，例如 verdict、score 和 explanation。 |
| **Measurement** | 从 Unit 提取的 token、耗时、调用量和资源用量等事实，不携带质量 verdict。 |
| **Worksheet** | 一次 EvaluationRun 基于 Dataset 的行式结果，为每个 Unit 追加 Finding、Evaluation 与 Measurement cell。 |
| **Report** | 从一个或多个 Artifact 派生的面向人渲染，不会重新执行 Experiment。 |
| **Verdict** | 人、CI 和 Agent 开发闭环共同消费的机器可读结论。 |

同一 Case 可以从多个角度观察。一次执行已经产生 response、性能采样、trace 或 trajectory 时，应将这些 Observation 固定为可复用 Dataset；选择不同 Detector、Evaluator、Measurer 或 Policy 即可生成新的 EvaluationRun、Worksheet 和报告，不重复执行系统。

## 共享平台工具箱

部分执行机制会服务多个 Harness。例如，恢复 E2E 和性能测试都需要可靠地发现 Kubernetes 工作负载、等待状态收敛并采集 Event 证据。Go `toolbox/kube` 与 Python async `harness_toolbox.kube` 对等提供 namespace-scoped 的 Kubernetes 控制与观测，但不拥有任何业务 Case、负载模型或 Verdict。Python 使用者通过可选依赖 `case-harness[kube]` 安装。

消费项目仍负责选择目标工作负载、决定何时允许注入故障，以及什么结果足以证明恢复或性能达标。其它故障注入后端可以继续加入工具箱，而不把实验意图从项目中搬走。具体边界和现有能力见 [Harness 工具箱](docs/toolbox.md)。

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
| case-harness | 执行机制、领域 Harness、Run 产物、报告基础设施、Verdict 契约、共享平台工具 |
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
| `go/toolbox/kube` / `python/harness_toolbox/kube` | e2e / perf 共用的 Kubernetes 控制与观测 |

## 仓库开发

```bash
cd python && uv sync && uv run pytest -q
cd ../go && go test ./...
cd ../typescript/trace-harness && bun install --frozen-lockfile && bun test
cd ../perf-harness && bun install --frozen-lockfile && bun test
```

## 状态

case-harness 仍处于早期公开阶段。canonical Case schema 来自 spec-case；`spec/` 下的 Verdict 与运行时契约是本仓库的稳定中心。不同语言 SDK 可以覆盖不同能力，但应持续遵守同一组契约。

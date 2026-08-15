# trajectory_harness 设计

## 1. 定位

trajectory_harness 回答的是：**agent 为得到结果而采取的决策与行动序列是否合理，以及一批
轨迹的执行质量如何变化**。

| 视角 | 主要问题 | 分析本体 |
|------|----------|----------|
| eval_harness | 最终回答好不好 | response / sample |
| trajectory_harness | 行动过程是否合理、失败和指标如何变化 | ordered Step / EvaluationRun |
| trace_harness | 物理链路哪层先反常 | span 投影出的 Node |

稳定处理链路为：

```text
Source
  -> TrajectoryLoader
  -> Trajectory (Step + Failure + ExecutionResult)
  -> Evaluator
  -> EvaluationResult (verdict + measurements)
  -> EvaluationRun (Dataset + evaluated trajectories)
  -> Metric
  -> Report / HTML
```

## 2. 轨迹事实

### 2.1 Trajectory 与 Step

`Trajectory` 是一次 agent/workflow 执行的有序步骤集合。`Step` 保留操作身份、父子关系、
顺序、耗时、状态及 OTel GenAI `role + parts` message。只有 Loader 知道来源格式；Evaluator
不读取 ATIF、OTLP 或框架私有字段。

轨迹不是 trace tree 的别名。trace_harness 保留物理遥测事实并分析错误传播与拓扑；
trajectory_harness 只保留 agent 决策和评估需要的语义步骤。

### 2.2 Failure 与 ExecutionResult

轨迹本身不保证成功。一个操作失败记录为：

```python
Failure(
    kind="tool",
    phase="prepare",
    error_type="dependency_missing",
    code="ENOENT",
    message="executable not found",
)
```

分类维度保持正交：

- `kind`：失败操作的类别，如 `llm / tool / agent / workflow`。
- `phase`：失败发生的阶段，如 `routing / request / resolve / prepare / execute`。
- `error_type`：可跨操作复用的低基数类型，如 `timeout / rate_limit /
  dependency_missing / permission_denied / unknown`。

完整 key（如 `llm.request.timeout`）只在查询和展示时派生。Provider 状态码、异常类名及原始
描述分别保留在 `code` 和 `message`，不膨胀稳定分类。

具体操作失败放在 `Step.failure`；整条轨迹的权威结果放在 `ExecutionResult`。某个 Step 失败但
最终 `outcome=completed` 表示流程已恢复；`ExecutionResult.failure` 只表达导致最终未完成的
主要失败。主动取消可以只有 `outcome=canceled`，不必伪装为 Failure。

## 3. 评估

### 3.1 Evaluator

确定性规则、reference match 和 LLM judge 都实现同一个 Evaluator 协议。`EvaluatorSpec`
声明稳定 id、说明、owner、`common/domain` 类型及可输出的 Measurement。

首批通用 Evaluator：

- `execution_success`
- `tool_success`
- `repeated_tool_call`

文件覆盖率、搜索范围、业务提交是否完成等规则仍由业务包提供；通用 Harness 只负责执行和
聚合，不理解业务工具语义。

### 3.2 EvaluationResult

一个 Evaluator 对一条轨迹返回一个 `EvaluationResult`：

- `status`：`evaluated / not_applicable / error`。
- `verdict`：`pass / fail / warning`。
- `score`：可选的归一化分数。
- `measurements`：该轨迹上的原始数值。
- `explanation / step_ids`：可读解释与证据锚点。

`not_applicable` 不按 0 分处理；Evaluator 异常使用 `status=error`，属于评估执行健康，不是
轨迹质量。Harness 不默认加权不同 Evaluator 的 score；如业务需要准入门槛或综合分，应显式
提供 Policy。

## 4. EvaluationRun 与 Metric

`EvaluationRun` 把一批轨迹评估绑定到 `DatasetRef`、run id、时间和 Evaluator 目录。run id
只是身份，趋势横轴使用 `created_at`；按周、按版本或按需运行都是调用方策略。Dataset
的版本和 slice 是 Metric 可比较性的组成部分，例如 CCR 的 Unit 与 Lane 应使用不同 slice。

Measurement 是单条轨迹上的原始测量；Metric 是 EvaluationRun 上的聚合结果。Metric 可以
来自三类事实：

```text
Trajectory / ExecutionResult -> completion rate, duration p95
Failure                      -> llm timeout rate, tool dependency-missing count
EvaluationResult             -> evaluator pass rate, mean score, measurement p95
```

Metric 使用 `name + aggregation + dimensions` 寻址，例如：

```text
execution.duration_ms.p95
failure.rate{impact=execution,kind=llm,phase=request,error_type=timeout}
evaluation.pass.rate{evaluator_id=repeated_tool_call}
evaluation.measurement.mean{evaluator_id=tool_success,measurement=success_rate}
```

多个 EvaluationRun 上同一地址的 Metric 按 `created_at` 构成趋势序列。报告接口也可直接
接收已经持久化的 Metric，因此生成历史趋势不需要重新加载完整轨迹。

## 5. 报告

trajectory_harness 拥有轨迹领域报告语义，对外提供 `build_report`、`render_report_html` 和
`write_report_html`。固定章节覆盖：

1. EvaluationRun 与 Dataset。
2. 执行结果与 Failure 分类。
3. common/domain Evaluator 目录。
4. 最新 Metric。
5. 多个 Run 的 Metric 趋势。

实现上先投影为 `harness_common.report_kit.Report`，再使用公共 HTML renderer。report_kit 只
理解 Section、Table、Chart 等中立文档块；业务可以追加 Section，但不自行维护 HTML 模板。

## 6. 外部语义

OTel GenAI semantic conventions 提供 operation、message 和 `error.type` 的外部词汇；
OpenInference/LangSmith 等实现也普遍把 LLM、Tool、Agent 操作类型与错误类型分开记录。
本项目据此使用薄 IR，但不依赖某个 OTel SDK，也不把仍在演进的外部生成类型直接作为内部
模型。

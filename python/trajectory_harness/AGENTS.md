# trajectory_harness

## 项目定位与边界

trajectory_harness 评估 agent/workflow 的**决策与行动序列**：是否反复调用同一工具、绕路、
遗漏必要步骤，或在某一步做了错误决定。一条 Trajectory 可以是单个 agent loop，也可以是多个
loop 与确定性操作构成的 pipeline。它不替代 eval_harness 的最终回答质量评分，也不替代
trace_harness 对物理 span、耗时与错误传播的归因。

外部 session / trace 先经 `TrajectoryLoader` 投影为稳定的 `Trajectory`，Evaluator 只消费
该中间格式，不感知 OTel、框架 session 或存储后端。轨迹事实、评估结论、批量指标和报告逐层
分离：Failure 不是低分，Measurement 也不是 Dataset 级 Metric。

## 代码地图与核心模块

```
trajectory_harness/
├── model.py             # Trajectory / Step / Failure / ExecutionResult
├── loaders/             # 外部记录 → Trajectory；base 契约 + OTel JSON 默认实现
├── evaluate.py          # EvaluatorSpec / EvaluationResult / DiagnosticSignal 与编排函数
├── metrics.py           # DatasetRef / EvaluationRun / Metric 与通用聚合
├── report.py            # 轨迹领域 Report 构建与 HTML 入口
├── evaluators/          # 确定性与模型 evaluator；一个文件一种判定
└── tests/               # 中间格式、loader 与 evaluator 契约测试
```

## 关键约定

- **OTel 是外部词汇，不是内部依赖**：operation 与 message parts 对齐 OTel GenAI 语义约定，
  但核心模型不依赖某个 OTel SDK 或仍在演进的生成类型。
- **只有 Loader 知道来源格式**：session/OTLP/框架私有字段止于 Loader；Evaluator 只读
  `Trajectory`。
- **多阶段仍是 Step tree**：`parent_step_id` 保留 agent/workflow 的执行层级；领域 Evaluator
  通过 `operation / name / attributes` 选择子树，通用模型不引入 Stage。
- **Failure 是执行事实**：具体操作失败放在 `Step.failure`，最终主要失败放在
  `ExecutionResult.failure`；分类使用 `kind / phase / error_type` 三个正交维度。
- **Evaluator 信号不回填 Failure**：`EvaluationResult` 是 Evaluator 的执行结果，行为线索写入
  `signals`，并用 `hypotheses` 表达可能原因；业务契约不合格使用 `verdict=fail`，`status=error`
  只表示 Evaluator 自身异常。
- **Evaluator 统一输出证据**：无法适用和 Evaluator 自身报错通过 `status` 表达，不能伪装为
  0 分；`verdict / score / measurements` 承载整体判定和测量，Signal 用自己的 `step_ids` 锚定
  现象证据。
- **通用 Evaluator 沉淀信号**：围绕 system prompt、tool set 和 loop mechanism 积累可复用
  的行为信号，但不把信号直接归因到某一组成；业务契约和跨 loop 编排由 domain Evaluator 负责。
- **Metric 只表示批量聚合**：单轨迹的原始值叫 Measurement；Metric 必须属于一个
  `EvaluationRun + DatasetRef`，才能跨版本和时间比较。
- **HTML 由 trajectory_harness 对外提供**：本包决定 Dataset、Failure、Evaluator、Metric
  与趋势章节，再投影到中立的 `harness_common.report_kit`；业务消费者不自行拼 HTML。
- 不新增 Operator / Engine 层：确定性规则、reference match 与 LLM judge 都实现同一个
  Evaluator；编排先保持为纯函数，出现真实生命周期后再升级。
- 不默认合成跨 Evaluator 综合分；需要门禁或总分时由业务显式定义 Policy。

## References

- 设计与外部实现取舍：[`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md)
- OTel GenAI 语义约定：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>

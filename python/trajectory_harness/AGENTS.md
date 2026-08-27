# trajectory_harness

## 项目定位与边界

trajectory_harness 评估 agent/workflow 的**决策与行动序列**：是否反复调用同一工具、绕路、
遗漏必要步骤，或在某一步做了错误决定。一条 Trajectory 可以是单个 agent loop，也可以是多个
loop 与确定性操作构成的 pipeline。它不替代 eval_harness 的最终回答质量评分，也不替代
trace_harness 对物理 span、耗时与错误传播的归因。

外部 session / trace 先由 `RecordingSource` 发现和读取，再经 `TrajectoryLoader` 投影为稳定的
`Trajectory`。Detector、Evaluator 与 Measurer 只消费该中间格式，不感知 OTel、框架 session
或存储后端。轨迹事实、
评估结论、批量指标和报告逐层分离：Failure 不是低分，Measurement 也不是 Dataset 级 Metric。

## 代码地图与核心模块

```
trajectory_harness/
├── model.py             # Trajectory / Step / Failure / ExecutionResult；含 generation provenance
├── source.py            # RecordingQuery / RecordingRef / RecordingSource
├── dataset.py           # versioned Trajectory Unit facts / annotation relation
├── build.py             # Source + Loader → 固定 Dataset；领域对齐 annotation
├── failures.py          # LLM 等通用低基数 Failure taxonomy 与构造函数
├── loaders/             # 外部记录 → Trajectory；base 契约 + OTel JSON 默认实现
├── detect.py            # DetectorSpec / DetectionResult / Finding 与发现编排
├── evaluate.py          # EvaluatorSpec / EvaluationResult 与判定编排
├── measure.py           # MeasurerSpec / MeasurementResult 与测量编排函数
├── metrics.py           # TrajectoryEvaluationRun / Metric 与 target/category 维度聚合
├── runner.py            # 固定 Dataset → Run（detection + evaluation + measurement）
├── runio.py             # dataset.json + 单次 run.json 持久化
├── report.py            # 纯 Run artifact → Report / HTML，历史外部加载
├── report_comparison.py # 调用方显式选 effect/cost 指标的 Pareto 投影
├── report_detection.py  # Detector catalog 与 Finding evidence 报告投影
├── report_provenance.py # generation provenance 分组与报告投影
├── verdict.py           # 运行健康 + 可选领域 Policy → verdict.json
├── pipeline.py          # Builder + Runner + Reporter 一键编排门面
├── detectors/           # 可复用行为模式发现；一个文件一种 Finding
├── evaluators/          # 确定性与模型 evaluator；一个文件一种判定
├── measurers/           # 单轨迹事实测量；一个文件一种测量关注点
└── tests/               # 中间格式、loader 与 evaluator 契约测试
```

## 关键约定

- **OTel 是外部词汇，不是内部依赖**：operation 与 message parts 对齐 OTel GenAI 语义约定，
  但核心模型不依赖某个 OTel SDK 或仍在演进的生成类型。
- **Source 只负责选择和读取**：Source 返回轻量 `RecordingRef` 和原始 `Recording`，不解析为
  `Trajectory`，也不执行判定；领域标签作为 `TrajectoryAnnotation` 与 Dataset 组合，不塞进 Source 契约。
- **Kernel 对齐**：Trajectory 是 Observation，`trajectory_id` 定义 Unit grain；`TrajectoryDataset` 固定 Case + Trajectory Unit 与 `TrajectoryAnnotation`。每次 `TrajectoryEvaluationRun` 记录实际选择的 Detector / Evaluator / Measurer / Policy，并只填充自己的 Worksheet；同一 Dataset 可按成本、效果或行为反复评估，详见 [`../../docs/kernel.md`](../../docs/kernel.md#dataset-与反复评估)。
- **Target 与 Category 正交**：`target` 表达一行当前评估谁，如 CCR 的 Review 1 / Review 2；Detector / Evaluator / Measurer spec 的 `category` 表达观察面，如 behavior / quality / cost。它们都是 Worksheet 与 Metric 的维度，不形成额外结果容器；报告通过 `group_by` 投影视图。
- **只有 Loader 知道来源格式**：session/OTLP/框架私有字段止于 Loader；Evaluator 只读
  `Trajectory`。Dataset Builder 把 Source 的 `recording_id` 写入轨迹的一等 provenance
  字段；`source` 保留 URI/path；`generation` map 记录实际产生行为的 agent、instruction/skill、
  tool contract、model、loop 与 orchestration 版本。它只是 Trajectory provenance，不形成独立
  领域对象，也不能由 Dataset 或 Evaluator version 反推。Source 与 Loader 通过内存文本组合，
  避免强制落临时文件。
- **多阶段仍是 Step tree**：`parent_step_id` 保留 agent/workflow 的执行层级；领域 Evaluator
  通过 `operation / name / attributes` 选择子树，通用模型不引入 Stage。
- **Failure 是执行事实**：具体操作失败放在 `Step.failure`，最终主要失败放在
  `ExecutionResult.failure`；分类使用 `kind / phase / error_type` 三个正交维度。
- **Detector Finding 不回填 Failure**：`DetectionResult` 是 Detector 的执行结果，诊断发现写入
  `findings`，并用 `hypotheses` 表达可能原因；业务契约不合格由 Evaluator 使用 `verdict=fail`，
  各组件的 `status=error` 只表示自身异常。
- **Detector、Evaluator 与 Measurer 不混用**：Detector 只输出 Finding，Evaluator 按契约输出
  可选 `verdict` 和/或 `score`，Measurer 只输出
  Measurement；无法适用和插件自身报错通过各自 `status` 表达，不能伪装为 0 分或 0 成本。不得用
  `*Evaluator` 命名只做事实测量的组件，也不得让 MeasurementResult 携带质量 verdict。
- **Finding 是诊断发现**：Finding 表示 Detector 解释出的具体问题模式，用 `step_ids` 锚定证据并用
  `hypotheses` 记录可能原因；可直接计数、求和的 token、调用次数和耗时仍是 Measurement。
- **通用 Detector 沉淀 Finding**：围绕 system prompt、tool set 和 loop mechanism 积累可复用
  的行为发现，但不把发现直接归因到某一组成；业务契约和跨 loop 编排由 domain Evaluator 负责。
- **Metric 只表示批量聚合**：单轨迹的原始值叫 Measurement；Metric 从某个 EvaluationRun 的
  Worksheet 聚合，并携带 Dataset version、组件 spec、run、target、category 等比较维度。
- **HTML 由 trajectory_harness 对外提供**：本包决定 Dataset、Failure、Evaluator、Metric
  与趋势章节，再投影到中立的 `harness_common.report_kit`；effect-cost Pareto 必须由业务显式选择
  两条 Metric 轴，Harness 不猜 effect。业务消费者不自行拼 HTML。
- **三段式生命周期**：`TrajectoryDatasetBuilder` 从 Source/Loader 构建带 annotation 的
  版本化 Dataset；`TrajectoryEvaluationRunner` 以实际选择的 Detector / Evaluator / Measurer / Policy 消费固定 Dataset；`TrajectoryReportBuilder`
  只消费已持久化 Run artifact。`TrajectoryHarness` 只是编排门面，不吸收领域逻辑。
- **Dataset 先于 Run，Run 先于视图**：`dataset.json` 保存可反复评估的 Unit facts 与 annotation，
  `run.json` 只保存本次评价并引用 Dataset 中的 trajectory id，`report.html` 是纯下游视图。
  历史 run 由 Reporter 外部加载，不复制进新 `run.json`；重渲染不能重新抓 Source 或运行插件。
- **Finding 不自动决定 Verdict**：没有领域 `TrajectoryVerdictPolicy` 时 run 为 `skipped`
  但仍产出分析产物；Dataset 构建或 Detector/Evaluator/Measurer 插件异常为 `error`。
- 不默认合成跨 Evaluator 综合分；需要门禁或总分时由业务显式定义 Policy。

## References

- 设计与外部实现取舍：[`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md)
- OTel GenAI 语义约定：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>

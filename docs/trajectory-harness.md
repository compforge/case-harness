# trajectory_harness 设计

## 1. 定位

trajectory_harness 回答的是：**agent 为得到结果而采取的决策与行动序列是否合理，以及一批
轨迹的执行质量如何变化**。

| 视角 | 主要问题 | 分析本体 |
|------|----------|----------|
| eval_harness | 最终回答好不好 | response / sample |
| trajectory_harness | 行动过程是否合理、失败和指标如何变化 | trajectory-keyed Worksheet |
| trace_harness | 物理链路哪层先反常 | span 投影出的 Node |

稳定处理链路是不断把不同来源的信息对齐到同一条 Trajectory，而不是在互不相干的模型之间搬运数据：

```text
RecordingSource
  -> Recording                         原始 record / trace，中间产物
  -> TrajectoryLoader
  -> Trajectory Observation            带 recording / case / run 来源身份的过程事实
       + TrajectoryAnnotation          人工、外部系统或模型提供的监督信息
  -> Trajectory Unit                   以 Case + Trajectory 为数据来源
  -> TrajectoryDataset                 可复用、版本化的 Unit facts
  -> Evaluator / Measurer / Policy
  -> TrajectoryEvaluationRun / Worksheet
       + EvaluationResult              向同行追加质量判断
       + MeasurementResult             向同行追加成本与运行事实
       + target / category dimensions  标识评估对象与观察面
       + aggregate Metrics             对 Worksheet 分组和聚合
  -> internal JSON / verdict.json / report.html
```

`Trajectory` 是 trajectory_harness 的 Observation，也是贯穿全链路的主记录；`trajectory_id` 是
Unit key 和 Worksheet 行键。它必须保留从 Recording、Case 和 Run 回溯所需的来源 identity，
并在 `generation` provenance map 中记录实际产生行为的 agent revision、instruction/skill、
tool contract、model、loop 与 orchestration 版本。这个 map 是 Trajectory 的来源字段，不是独立
领域对象；真实值由 Loader 或项目 wrapper 填写，Harness 不从 Dataset 或 Evaluator version 推断。
Dataset Builder 负责把 Case seed、人工 label、reference 和
LLM 生成的监督信息对齐到 Unit，形成可反复评估的 TrajectoryDataset。每组实际选择的 Detector、
Evaluator、Measurer 与可选 Policy 分别产生自己的 EvaluationRun / Worksheet；报告只对 Worksheet 做筛选、分组、聚合和展示，不重新
读取 Source，也不重新解释原始 trace。

这里的“大表”是逻辑模型，不要求 JSON 把整条 Trajectory 在每个结果中重复一遍。Dataset 保存
Trajectory 与 Annotation seed，Run 保存本次 Detection、Evaluation 与 Measurement，再通过 `trajectory_id`
无损恢复 Worksheet；同一 Dataset 可以对应多张不同侧重点或不同 evaluator 版本的 Worksheet。

这里评估的对象是一次面向目标的 agent/workflow 执行。一个 Trajectory 可以只包含一个 agent
loop，也可以包含由多个 agent loop 和确定性操作共同组成的 pipeline。每个 agent loop 的行为通常由
三部分共同决定：

1. system prompt：目标、约束和行为指令；
2. tool set：可用能力、描述、参数与返回契约；
3. loop mechanism：上下文压缩、停止条件、轮次或时间预算等运行策略。

Trajectory 是这些 loop 配置及其编排共同作用后的运行证据，不要求 Loader 反推出某个行为究竟由哪一段
配置单独造成。通用模型只有一种 Trajectory，不区分 root / child 类型；本次 Dataset 选择的执行边界
就是一行的 Trajectory。多个 loop 通过 `Step.parent_step_id` 组成执行层级；`operation / name / attributes`
标识 agent、workflow、LLM 和 tool 等操作。具体业务可以据此选择某个 Step 子树或整条 Trajectory
进行评估，无需让通用 Harness 理解 Review 1、Review 2 等领域阶段。

Detector 逐步沉淀可复用的 Finding，Evaluator 负责效果与契约判定，Measurer 独立记录 token、
调用量与耗时等事实，再由实验
或业务 Policy 判断应修改 prompt、tool、loop mechanism 还是 pipeline 编排。单个行为模式通常只是
Finding；除非存在明确契约，不能直接把它定性成 Failure。

### 1.1 Source 与 Loader 边界

`RecordingSource` 统一“从哪里找轨迹原料”：`select(RecordingQuery)` 返回只含身份、URI、时间和
低成本属性的 `RecordingRef`，`fetch(ref)` 才读取完整原始文本。公共 Query 只提供时间、精确属性
和数量上限；仓库、租户等领域过滤可由具体 Source 扩展。

Source 不理解 ATIF、OTLP 等格式，不构造 `Trajectory`，也不拥有人工标签。格式解析属于
`TrajectoryLoader`；forge comment 等监督信号属于 `TrajectoryAnnotation`，由业务 Dataset builder
通过 `trajectory_id` 与主记录连接。一个 Annotation 可以关联一条或多条 Trajectory，也可以暂时没有
匹配结果，从而保留“监督信息已存在，但原始记录拉取或解析失败”的事实。Loader 同时提供文件 `load`
与内存文本 `loads`，因此远端 API、CLI 导出或本地 session Source 不需要先创建临时文件。

### 1.2 Tool set 的两个评估层级

Tool 不能只按“调用成功或失败”评估，还要区分单个工具契约和整个工具集：

1. **单工具契约质量**：tool name 是否准确表达能力，description 是否帮助模型判断适用边界，
   argument schema 是否清晰且约束恰当，result 是否便于模型继续决策。轨迹上的无效参数、schema
   错误、换参数重试和调用后立即纠正，是模型能否稳定生成合理调用的证据。
2. **工具集覆盖与效率**：tool portfolio 是否覆盖该行业或任务中反复出现的高价值动作，工具之间
   是否存在明显空白、重叠或选择歧义。`read / write / edit / bash` 等最小通用工具集可能足以完成
   任务，却不一定高效；模型反复借助 shell 安装依赖、拼接临时命令或绕行多步完成固定动作，会表现为
   轨迹变长，是缺少专用工具或批量能力的候选 Finding。

第二类判断需要任务和行业上下文。通用 Harness 可以测量无效参数率、重试、连续调用、通用执行器
占比和轨迹长度，但不内建“某个行业必须有哪些工具”的清单；期望的 tool portfolio 及其契约由 domain
Evaluator 或 Dataset 提供。一个通用工具被频繁使用也不自动说明工具集有问题，只有与 case 类型、
替代路径、耗时和结果质量结合后，才能形成 warning 或 fail verdict。

## 2. 轨迹事实

### 2.1 Trajectory 与 Step

`Trajectory` 是一次 agent/workflow 执行的有序步骤集合。`Step` 保留操作身份、父子关系、
顺序、耗时、状态及 OTel GenAI `role + parts` message。单个 agent loop 或 pipeline 中的一个
agent 节点都表示为 Step 子树；通用模型不额外定义 Stage。只有 Loader 知道来源格式；Evaluator
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

常见 LLM 失败由 `llm_failure(phase, error_type)` 统一构造，timeout 可用
`llm_timeout(phase)` 缩窄到已观测的请求进度边界。公共 error type 包括 `timeout /
rate_limit / client_error / server_error / network_error / invalid_response / unknown`。Harness
只拥有稳定词汇，不猜测 provider 错误文本；原始错误到 Failure 的分类仍由 Loader 完成。

LLM timeout phase 使用客户端可观测的边界，不反推服务端内部根因：

| phase | 含义 |
|-------|------|
| `routing` | 路由、端点选择或多次 attempt 共享的总预算耗尽 |
| `connection_pool` | 未在时限内取得客户端连接池连接 |
| `connect` | DNS / TCP / TLS 等建连过程超时 |
| `request_write` | 请求 header/body 尚未写完 |
| `first_chunk` | 流式请求写完后，首个非空响应 chunk 未在时限内到达 |
| `inter_chunk` | 已收到输出后，下一个响应 chunk 未在时限内到达 |
| `request` | 整体 request/route deadline 耗尽，而来源无法提供更细进度 |

`first_chunk` 对齐 OpenTelemetry 客户端的
[`gen_ai.client.operation.time_to_first_chunk`](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/gen-ai/gen-ai-metrics.md)；
HTTP 传输层的 pool/connect/write/read 划分与
[HTTPX timeout](https://www.python-httpx.org/advanced/timeouts/) 一致。已经开始流式输出后的“无进展”
对应 [inter-chunk latency（ICL）](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference)
的观测边界以及 Envoy 的
[`per_try_idle_timeout`](https://www.envoyproxy.io/docs/envoy/latest/api-v3/config/route/v3/route_components.proto.html)
语义。

TTFT、ITL/TPOT 和 end-to-end latency 是 Measurement，不是天然的 Failure 类型。TTFT 包含网络、
排队、prefill 和首 token 生成；ITL/TPOT 是输出 token 间延迟的聚合值。只有调用方对这些
边界实际执行 deadline 时，才产生 `first_chunk` 或 `inter_chunk` timeout Failure；“TPOT 偏高”
本身应由 Measurer 输出 Measurement；只有识别出稳定行为模式后才形成 Detector Finding。vLLM
服务端进一步暴露 queue、prefill 和 decode 时间，
这些数据可作为 Step attributes 帮助归因，但客户端 Loader 不应凭 TTFT 猜测其中哪一段超时。

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
声明稳定 id、说明、owner、`common/domain` 类型和 category；Runner 根据每个 Trajectory Unit 的
target 选择适用 Evaluator，并把 target/category 写入 Worksheet 结果。

首批通用 Evaluator：

- `execution_success`
- `tool_success`

首批通用 Detector：

- `repeated_tool_call`
- `retry_loop`
- `post_compact_refetch`

其中 `repeated_tool_call` 输出诊断 Finding，提示检查缓存、复用或批量参数的机会；重复调用
本身不等于错误。`retry_loop` 保留最终成功可能掩盖的失败重试，`post_compact_refetch` 只判断
compact 前后完全相同的工具调用；外部资源是否必须刷新仍是待验证假设。

文件覆盖率、搜索范围、业务提交是否完成等规则仍由业务包提供；通用 Harness 只负责执行和
聚合，不理解业务工具语义。

### 3.2 围绕 Agent Loop 积累 Finding

trajectory_harness 持续沉淀可跨业务复用的 Detector，其 Finding 可以帮助检查 agent loop 的
三个组成面：

| 观察面 | 可沉淀的通用 Finding | 业务 Evaluator 负责的判断 |
|--------|------------------------|--------------------------|
| system prompt | 目标偏离、指令重试、过早结束、输出格式反复自我修正 | 领域指令和结果契约是否真正被违反 |
| tool set | 工具执行失败、无效参数、换参重试、连续重复调用、通用执行器绕行 | 领域工具集是否缺失、重叠或不符合任务契约 |
| loop mechanism | 预算耗尽、timeout、压缩压力、停止不收敛、过早结束 | 具体轮次、时间、压缩和停止策略是否合理 |

这个对应是多对多的诊断索引，不是根因归属。例如连续重复调用同一 tool 是 Finding；它可能暗示
工具缺少批量参数、prompt 未要求复用结果，或 loop 没有合适的停止机制，这些候选解释记录为
`hypotheses`。Detector 只输出可复现的现象、证据和假设，根因由对照实验或业务 Policy 确认。

新的通用 Detector 应在 `detectors/` 中按一种稳定 Finding 一个实现沉淀；依赖行业工具清单、
业务阶段或特定结果契约的判断留在 domain Evaluator。pipeline 可以包含多个 loop，跨 loop 的
编排与协作 Finding 同样由 domain Detector 先行沉淀，出现稳定跨业务模式后再上收为通用实现。

### 3.3 DetectionResult 与 EvaluationResult

一个 Detector 对一条轨迹返回一个 `DetectionResult`：

- `status`：`analyzed / not_applicable / error`。
- `findings`：零到多个诊断发现；每个 Finding 包含稳定 `code`、`severity`、摘要、
  `step_ids` 证据及可能原因 `hypotheses`。
- `explanation`：Detector 的适用性或执行说明。

一个 Evaluator 对一条轨迹返回一个 `EvaluationResult`：

- `status`：`evaluated / not_applicable / error`。
- `verdict`：`pass / fail / warning`。
- `score`：可选的归一化分数。
- `explanation / step_ids`：可读解释与证据锚点。

`not_applicable` 不按 0 分处理；Evaluator 异常使用 `status=error`，属于评估执行健康，不是
轨迹质量。Harness 不默认加权不同 Evaluator 的 score；如业务需要准入门槛或综合分，应显式
提供 Policy。

Failure、Detector 发现与 Evaluator 判定是三条独立轴：`Step.failure / ExecutionResult.failure`
只记录运行时已经发生的失败事实；Detector 发现的行为模式写入 `DetectionResult.findings`，可能原因只是
Hypothesis，不是已确认 Issue。存在改进可能但尚不能判错时使用 `verdict=warning`；业务契约明确
认为该行为不合格时使用 `verdict=fail`。这里不使用 `verdict=error`，因为 `status=error` 专门表示
Evaluator 自身执行异常。报告分别展示 Failure 与 Evaluator 结果，不能把 warning/fail 反写成
轨迹 Failure。

`Finding` 是 Detector 对证据作出解释后识别的具体问题模式，不是可任意聚合的原始数值。
它使用稳定 `code` 表示模式、`step_ids` 指向证据，并用 `hypotheses` 保存尚未确认的可能原因。token、
调用次数、时长等能直接计数或求和的观测必须进入 Measurement；如果一个 Finding 只是在换名字包装
原始事实，就不应作为 Finding。

Failure 在评估前已经由 Loader 确定，Evaluator 不修改它。TrajectoryEvaluationRun 通过 Worksheet
行键连接 Failure、Trajectory 和 Dataset，既可按 target 聚合 `llm.request.timeout` 比例，也可在报告中
回看受影响的具体 trajectory/case。诸如“长上下文更容易 timeout，可能暴露 inference 能力不足”属于
基于 Failure 与 case 特征的关联和归因假设，不属于 Failure 本身。

### 3.4 Measurer 与 MeasurementResult

Measurer 只观察事实，不判断质量。`MeasurerSpec` 声明稳定 `measurer_id`、category 及其可输出的
`MeasurementSpec`；`MeasurementResult` 使用 `measured / not_applicable / error` 表达测量执行状态，
并携带 Measurement、解释及证据 step。它不包含 verdict、score 或 Finding。反过来，EvaluatorSpec
和 EvaluationResult 也不声明或携带 Measurement。

通用 Measurer 分别观察模型、工具与上下文使用：

- `ModelUsageMeasurer`：模型调用、input/output/cache token 与使用量覆盖率；
- `ToolUsageMeasurer`：执行次数、Failure、耗时、result bytes、result 覆盖率与已观测并发；
- `ContextUsageMeasurer`：input token 首尾/峰值变化、compact 次数及 compact 边界前后的 input delta。

这些值不判断一次读取、压缩或调用是否必要；命名和类型共同表达边界，不提供所谓
“measurement-only evaluator”。

### 3.5 成本与效果联合解释

模型调用次数、input/output/cache token、耗时和工具调用次数都是 Measurement，不天然代表好坏。
相同成本可能用于完成更难的任务，也可能来自重复读取、失败重试或上下文膨胀；因此这些原始量默认使用
`direction=neutral`。通用 Detector 可以另外输出重复调用、失败重试、上下文增长等可复现 Finding，
但不能只因为 token 更多就判定轨迹更差。

成本优化必须和效果放在同一 Dataset/Cohort 中比较。以 CCR 为例，通用 Harness 负责记录每条 Review
轨迹的 token、模型调用、完成状态和行为 Finding；CCR 的 domain Dataset/Evaluator 再把这些事实与
Review 1/Review 2、finding 人工标签、missed finding 等监督信号对齐，比较有效 finding rate、wrong
rate、completion/timeout 与单位有效 finding 成本。有限时间或 token 预算下，减少非必要读取、重复
调用和无效重试也可能提高 completion，从而同时改善成本与效果；这种结论必须来自同 workload 的对照，
不能由单条轨迹的低 token 值直接推出。

`ModelUsageMeasurer` 只输出事实与覆盖率，不内建价格表。货币成本依赖 provider、模型、时间、缓存
计费和长上下文阶梯价，应由带 pricing provenance 的消费侧 Measurement 逐调用计算后再聚合，未知
价格保持 unknown，不能静默当作零成本。

报告可以由业务通过 `ParetoSpec` 显式选择一条 effect Metric 与一条 cost Metric，展示 completion、
duration p95 和支配关系。Harness 不从 category 或 direction 自动猜测业务 effect；存在多个 target
或 evaluator 时，选择器必须把维度限定到唯一 Metric。

## 4. Trajectory Dataset 与 Worksheet

`TrajectoryDataset` 是可复用、版本化的 Unit facts 集合；其中 Trajectory 是 Observation，Case 与
Trajectory 是 Unit 的数据来源，`trajectory_id` 是稳定 Unit key。Dataset 先固定 Unit 和已有监督
信息；每个 EvaluationRun 再以相同 grain 建立 Worksheet，并填充本次结果列：

```text
Trajectory Unit
├── case                        input / expected behavior / dimensions
├── observation: trajectory     ordered steps / execution result / source identity
└── annotations[]               human / external / LLM-provided supervision

EvaluationRun Worksheet row
├── unit                         dataset seed by trajectory_id
├── detections[]                detector findings
├── evaluations[]               evaluator verdict and/or score
└── measurements[]              token / latency / calls / resource facts
```

每条 `Trajectory` 通过一等 `recording_id` 保留它从哪份 Recording 投影而来，`source` 保留
URI/path；同一 Recording 解析出的多条轨迹共享 recording id。`TrajectoryAnnotation` 通过
`trajectory_ids` 把 MR comment label、reference 等监督信息连接到一条或多条主记录。Annotation
也可以暂时没有匹配到 trajectory，以保留“label 已存在，但 Recording 获取或解析失败”这一事实；
它不能因此被静默丢弃。

数据的生产者和数据的语义是两条独立轴。人工和外部系统通常产生 Annotation；LLM 既可以产生待评估
的监督信息，也可以作为 Detector 或 Evaluator 的实现。前者仍是 Annotation，后两者分别输出
DetectionResult 与 EvaluationResult。Finding、verdict 和 score 不回填 Annotation；Measurer 的原始事实也不伪装成
Evaluation。

`TrajectoryDataset` 固定 `Unit + Annotation` seed。`TrajectoryEvaluationRun` 把本次实际选择的
Detector / Evaluator / Measurer / Policy 施加到确定的 Dataset version，记录组件 spec 与配置，
为同一批 Unit 填充 Detection、Evaluation 和 Measurement 列：

```text
TrajectoryEvaluationRun
├── trajectory_ids[]
├── trajectory_targets[]
├── detections[]           target + category + detector results
├── evaluations[]          target + category + evaluator results
├── measurements[]         target + category + measurement results
└── metrics[]              dimensions 上的聚合结果
```

`target` 回答“当前行评估谁”，例如 CCR 的 Review 1 / Review 2；`category` 回答“从什么观察面看”，
例如 quality / cost。EvaluatorSpec 与 MeasurerSpec 声明稳定 category，Runner 从 Trajectory Unit
确定 target。两者只是 Worksheet 与 Metric 的正交维度，不拥有独立生命周期，也不形成额外结果容器。
报告通过 `group_by(target)`、`group_by(category)` 或两者组合产生比较视图。

Dataset 是可复用事实底座，Worksheet 是某个 EvaluationRun 的填表状态与结果。两者通过
`trajectory_id` 无损连接，但 Evaluation 和 Measurement 不写回 Dataset。Case、Trajectory 或
Annotation 变化会形成新的 Dataset version；只更换 evaluator、judge model、成本口径或分析侧重点，
应复用 Dataset 并产生新的 EvaluationRun。run id 表示一次填表过程，趋势横轴使用 `created_at`；
Dataset version、实际组件 spec、target 和 category 共同构成结果可比较性。

Measurement 是单条 trajectory row 上的原始测量；Metric 是对 Worksheet 按 run 或 dimension
聚合后的结果。Metric 可以来自四类事实：

```text
Trajectory / ExecutionResult -> completion rate, duration p95
Failure                      -> llm timeout rate, tool dependency-missing count
EvaluationResult             -> evaluator pass rate, mean score
MeasurementResult            -> token sum, model-call p95, usage coverage
```

Metric 使用 `name + aggregation + dimensions` 寻址，例如：

```text
execution.duration_ms.p95
failure.rate{impact=execution,kind=llm,phase=request,error_type=timeout}
evaluation.pass.rate{target=review1,category=quality,evaluator_id=repeated_tool_call}
measurement.value.sum{target=review1,category=cost,measurer_id=model_usage,measurement=input_tokens}
```

多个 TrajectoryEvaluationRun 上同一地址的 Metric 按 `created_at` 构成趋势序列。报告接口也可直接
接收已经持久化的 Metric，因此生成历史趋势不需要重新读取 Source 或重跑 Evaluator。

### 4.1 Dataset 与 Run 模型产物

`TrajectoryHarness` 把 Dataset 和 EvaluationRun 规范化保存到 `runs/<scope>/<run-id>/`。文件拆分
是为了复用和避免重复大体积轨迹，不改变“一行一个 trajectory_id”的 Worksheet grain：

- `dataset.json`：Worksheet 的固定 seed，包含 Trajectory、TrajectoryAnnotation、RecordingQuery
  与构建健康。
- `run.json`：本次 TrajectoryEvaluationRun，Detection/Evaluation/Measurement 通过 trajectory id 引用 Dataset，
  不重复存轨迹。
- `report.html`：从 Worksheet 纯投影出的 UI-friendly 视图。
- `verdict.json`：跨 Harness 统一出口；Finding 不自动成为 check，无领域 Policy 时为 `skipped`。

生成周报或版本报告时，`TrajectoryReportBuilder` 从 `history_dirs` 只读加载历史。
历史不写入当前 `run.json`，避免每周复制全量旧轨迹导致 O(n²) 存储和来源混淆。
纯重渲染只需 Reporter 和持久化产物，不需要 Source、Loader、Evaluator 或 Measurer 实例。

生命周期分为三个可独立使用的阶段，一键门面只做编排：

```text
TrajectoryDatasetBuilder:   select -> fetch -> load -> annotation join -> versioned Dataset
TrajectoryEvaluationRunner: Dataset + Detectors / Evaluators / Measurers / Policy -> Worksheet -> Run + Metric
TrajectoryReportBuilder:    Worksheet + external history -> Report IR -> report.html
```

领域只负责 Dataset Builder 的 annotation join、Runner 的 target/插件选择、可选 Verdict Policy，
以及 Reporter 的业务 `Section`。GitHub MR、comment label、Review 1/2 等概念因此留在
CCR，不进入 trajectory_harness；HTML 模板和数据到视图的控制流则只有 Harness 一份。

## 5. 报告

trajectory_harness 拥有轨迹领域报告语义，对外提供 `build_report`、`render_report_html` 和
`write_report_html`，并由 `TrajectoryReportBuilder` 提供持久化产物到 HTML 的纯构建入口。固定章节覆盖：

1. TrajectoryEvaluationRun、Dataset 及 target/category 维度。
2. 执行结果与 Failure 分类。
3. common/domain Detector 目录与 Detection/Finding evidence。
4. common/domain Evaluator 目录与 Evaluation evidence。
5. Measurer 目录与 Measurement evidence。
6. 最新 Metric。
7. 多个 Run 的 Metric 趋势。
8. Source/Loader 的 Dataset build health（通过一键 Harness 生成时）。

实现上先投影为 `harness_common.report_kit.Report`，再使用公共 HTML renderer。report_kit 只
理解 Section、Table、Chart 等中立文档块；业务子类可以从持久化模型追加 Section，但不自行维护
HTML 模板。这个“模型产物先落盘、报告可独立重建”的做法与 perf_harness 的 run model/report
分层一致；各 Harness 仍拥有自己的生命周期，不引入跨 Harness 的通用 Engine。

## 6. 外部语义

OTel GenAI semantic conventions 提供 operation、message 和 `error.type` 的外部词汇；
OpenInference/LangSmith 等实现也普遍把 LLM、Tool、Agent 操作类型与错误类型分开记录。
本项目据此使用薄 IR，但不依赖某个 OTel SDK，也不把仍在演进的外部生成类型直接作为内部
模型。

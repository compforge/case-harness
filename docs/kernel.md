# case-harness 内核

> 本文描述 case-harness 长期稳定的核心模型、测试边界和依赖方向。
> 当前已实现 Case 驱动的 API / eval / perf 等 harness；Playbook 驱动的功能测试是长期边界，尚未实现。

## 1. 理念

产品定位通常比用户需求稳定，用户需求和对外契约又比实现代码稳定。测试资产应锚定在这些更稳定的意图和契约上，而不是跟着内部类名、函数名和文件路径变动。

case-harness 的价值不是再提供一个测试 runner，而是让稳定的测试意图能够持续积累、可重复执行，并将结果收敛为统一 Verdict。大规模改动或发版前重跑外层测试，是为了分别回答：

- 用户还能否完成这个产品功能；
- 产品后端功能是否仍可用；
- 单个服务的对外 API 契约是否仍成立。

测试边界与判定视角是两根正交的轴：Web / App 功能、产品 API 功能、服务 API 契约回答“从哪个边界验证”；e2e / eval / perf / trace / trajectory 回答“从哪个视角观测和判定”。

## 2. 核心概念

| 概念 | 语义 |
|---|---|
| **Case** | 一个可重用的结构化测试输入，具有稳定 `case_id`；与 sources、facet vocabulary 一起归属 canonical CaseSet，可被 e2e、eval、perf 等不同视角消费。 |
| **Observation** | 执行 Case 后实际观察到的领域事实，例如 response、outcome、perf sample、trace 或 trajectory。它可以直接产生，也可以从 recording 等中间产物归一化而来；必须保留来源 identity 与 provenance，不包含质量判断。 |
| **Unit** | Harness 声明的评估单元，也是 Worksheet 一行所代表的基本粒度；其数据来源是对齐后的 Case 与一个或多个 Observation。Unit 拥有自己的稳定 key，唯一确定一行；Observation 尚未产生或失败时，该行可以保留 pending / failed 状态。 |
| **Annotation** | 运行当前评估前已经存在的人工、外部系统或模型监督信息，例如 label、reference 和复核结论；按 Unit 对齐并保留 producer 与 provenance。 |
| **Dataset** | 一组可复用、版本化的 Unit facts，固定 Case、Observation、Annotation 及其来源关系，不包含某次 EvaluationRun 的 Evaluation 或 Measurement。相同 Dataset 可以按不同侧重点反复评估。 |
| **EvaluationRun** | 对一个确定 Dataset version 执行一组 Evaluator、Measurer 与可选 Policy 的运行实例；它记录实际组件的 spec、模型、规则、版本和配置，并拥有 run identity、执行健康与对应 Worksheet。 |
| **Evaluation** | Judge / Evaluator 对 Unit 作出的质量判断，包括状态、verdict、score、explanation 和 Finding；使用确定性规则还是 LLM 是实现方式，不改变其语义。 |
| **Measurement** | 从 Unit 直接提取的 token、耗时、调用量和资源用量等中性事实，不携带质量 verdict。 |
| **Worksheet** | 一个 EvaluationRun 的行式工作模型：以 Dataset Unit 为行，保存 seed 事实以及本次追加的 Evaluation、Measurement 和 cell state。它是生成报告和聚合指标的事实输入，不等于某一种物理文件格式。 |
| **Playbook** | 用自然语言表达的产品功能测试剧本：用户目标、前置条件、有序动作、关键检查点和最终验收结果。它与 Web / Android / iOS / API 等执行目标解耦。 |
| **Script** | Playbook 针对某个 Target 编译出的可执行代码。它是可 review、可重放、可再生成的派生产物，不是功能需求的事实源。 |
| **Target** | 脚本真正操作的系统边界，例如 Web、Android、iOS、产品 API 或单服务 API。Target 决定 Script 使用的 SDK / Driver 和可观测证据。 |
| **CaseRun** | 一条 Case 在某个环境和 variant 上的运行实例；拥有 prepare/execute/judge/cleanup 生命周期、阶段预算和证据。 |
| **Run** | 一次真实执行的生命周期和产物边界，记录输入版本、Target、环境、输出、证据和对齐键。Experiment / Arm / Trial 是在 Run 之上组织对照的编排语义。 |
| **Report** | Worksheet 的下游投影；JSON 面向机器和内部系统，HTML 面向人。Report 不重新执行 Case、读取远端 Source 或运行 Evaluator。 |
| **Verdict** | 对一次 Run 的可机器消费判定。人、CI 和 agent 开发循环都通过它判断是否通过、为何失败，以及下一步应读哪些证据。 |

### 为什么叫 Playbook，不叫 Scenario

`Scenario` 通常表示一个具体条件下的单个示例，容易与已有 Case 概念重叠。`Playbook` 更强调为了达成某个用户目标而执行的有序动作、检查点与清理流程，也更适合作为多个 Target Script 的稳定源。

当前不预先建立“Playbook 包含多个 Scenario”的层级。只有真实功能测试出现需要独立标识、单独编排的多个变体时，Scenario 才值得成为下一层概念。

## 3. 主流程

### Case 路径（当前主路径）

```text
CaseSet + execution overlay（选择 / variant / 环境）
    → Case + Variant
    → CaseRun(prepare → execute → judge → cleanup)
    → Observation → Unit → Dataset
    → Dataset + Evaluators / Measurers / optional Policy
    → EvaluationRun → Worksheet
    → Verdict + Report
```

CaseSet 是资产边界；Experiment 的执行 overlay 只叠加选择、负载和环境等运行参数，不覆盖 Case 的
input、facets、sources 或 judgment。CaseRun 承担环境相关的过程；prepare/cleanup 不进入 Case，cleanup
总执行并使用独立预算，失败必须进入 Verdict error。Unit identity 可以在 Observation 产生前确定，
Dataset build 也可以保留 missing / failed Observation，不能为了得到“干净数据”而丢失执行失败。
E2E 等 Harness 可以在 CaseRun 内联执行所选 judge；落盘时仍须区分 Dataset
facts 与 EvaluationRun results，才能在不重新 execute 的情况下离线复判。

### Dataset 与反复评估

所有 Harness 都按同一组顶层概念组织数据：先基于 Case 得到真实 Observation，以两者为数据来源建立
评估 Unit，再将一组 Unit 固定为可复用 Dataset。每次运行选择的确定性规则、LLM Judge、Measurer
与可选 Policy 直接定义评估侧重点；每次 EvaluationRun 形成自己的 Worksheet 和 Report。

```text
Case + Variant / Arm / Environment
    -> Action / Run
       -> Observation                           直接产出
       -> intermediate artifact -> Observation  经采集、转换或归一化后产出
          response / outcome / samples / trace / trajectory
          + source identity / provenance
    -> Unit                                    evaluation unit
       <- Case + Observation                   aligned data sources
       + Annotation
    -> Dataset                                 versioned Unit facts

Dataset + Evaluators / Measurers / Policy A -> EvaluationRun A -> Worksheet A -> JSON / HTML
        + Evaluators / Measurers / Policy B -> EvaluationRun B -> Worksheet B -> JSON / HTML
        + Evaluators / Measurers / Policy C -> EvaluationRun C -> Worksheet C -> JSON / HTML

Worksheet row
    = Unit seed
    + evaluations
    + measurements
    -> aggregate / pivot
    -> metrics / verdict.json / report
```

Dataset 和 Worksheet 使用相同 Unit grain。Eval 通常以 `arm_id × case_id` 为 Unit，Trajectory 以
`trajectory_id` 为 Unit；Perf、Trace 和 E2E 按各自稳定的 request/window、trace 或 case-run identity
定义 Unit。一个 Harness 存在多种基本粒度时，应形成多个明确 grain 的 Dataset / Worksheet，不能把
request、window、run 等不同层级的行混进一张无从解释的大表。

一个 Case 可以产生一个或多个 Observation；直接产出的 response、outcome 与经过采集、转换后形成的
trace、trajectory 在这一层没有本质差别。Observation 必须携带足够的来源 identity 和 provenance，
使其能够稳定对齐原始 Case、Run 和中间产物，不能依赖文件名或报告渲染阶段猜测关系。Case 提供输入、
预期、facets 和 ground truth 等稳定 seed，Observation 提供系统实际做了什么；Unit 在 Harness 声明的
grain 上将两者形成独立、可寻址的评估单元。

Dataset 固定 Unit facts 和已有 Annotation；EvaluationRun 只向 Worksheet 同行追加不同语义的列族：

- **Annotation**：人工、外部系统或模型预先提供的 label、reference 与复核信息；保留 producer 和
  provenance。数据由 LLM 生成并不会自动使它成为 Evaluation，语义取决于它是否在表达监督信息。
- **Evaluation**：Judge / Evaluator 对 Unit 作出的质量判断、分数和 Finding；即使内部调用
  LLM，它仍属于 Evaluation。
- **Measurement**：从 Unit 直接提取的 token、耗时、调用量和资源用量等中性事实。

Case、Observation 或 Annotation 改变会形成新的 Dataset version；只更换 Evaluator、Measurer、模型、
规则、成本口径、Policy 或分析侧重点，应创建新的 EvaluationRun 并复用原 Dataset。EvaluationRun
必须记录实际运行的组件 spec 与配置，以支持复现和比较。Metric
是对已填充 Worksheet 按 run、slice、facet 或其它维度聚合后的结果，不是另一份与行数据脱节
的事实源。报告层只做 join、pivot、aggregate 和 render，不重新执行 Case、不重新读取远端 Source，
也不重新运行 Judge。内部 JSON 保存无损、可恢复的数据，`verdict.json` 是统一机器判定投影，HTML
是面向人的 UI 投影；需要 CSV 等格式时也从同一 Worksheet 派生。

所有 Harness 必须能映射到这套共同语义，但不要求共享同一个 `Dataset` / `Unit` / `Worksheet` 类或
schema。各 Harness 拥有自己的 Unit grain、强类型 key、列类型、调度和聚合语义；物理实现也可以把
Dataset build、Observation production 和 Evaluation 融合在一个带 cell state 的 Worksheet/checkpoint
中，只要事实列与本次评估列可分离，并能在不重新执行 Case 的情况下复用 Observation 重新评估。
`harness_common.report_kit` 只拥有中立报告 IR 与 HTML 渲染，不能反向拥有 Case、Trajectory、Trace
或 Metric 等领域模型。

各 Harness 对顶层概念的映射如下。表中的名字描述稳定语义，不要求实现公开同名 class：

| Harness | Observation | Unit grain / key | Dataset | Run components | Worksheet |
|---|---|---|---|---|---|
| e2e | Runner `Outcome` 与阶段证据 | 一次 CaseRun / `case_id + variant` | 可复判的 CaseRun Unit 集 | assertion / deterministic judge / soft metric 配置 | Unit + assertion Evaluation + timing Measurement |
| eval | 某 Arm 的 response、retrieval、citation 与调用观测 | `arm_id + corpus + case_id` | 已完成 solve cell 的 Unit 集 | scorer / metric / weight / judge model 配置 | 当前 table-centric Worksheet；score cell 是 Evaluation 或 Measurement |
| perf | request Outcome、probe sample 及其 window-aligned 归约事实 | 一个明确的 request、window 或 run grain；不同 grain 分表 | 可离线重算的 raw/model Run facts | Workload judge、SLO 与 analysis 配置 | 指定 grain 的 Unit + verdict / measurement / caveat |
| trace | raw span 归一、assemble 后得到的 `Node` | `trace_id + node_id` | nodes / corpus 中的 Node Unit 集 | detector 与 gate 配置 | Node facts + Finding Evaluation；trace/cohort Metric 为聚合 |
| trajectory | Recording 经 Loader 得到的 `Trajectory` | `trajectory_id` | `TrajectoryDataset`，含 Unit 与 Annotation | Evaluator / Measurer / slice / Policy 配置 | Trajectory Unit + Evaluation + Measurement |

E2E 等路径可以在执行后立即评估并只落一个 Run 目录；Eval 等引擎也可以用一张带 cell state 的
Worksheet 同时推进 Observation production 与 Evaluation。它们仍须能够区分 Dataset facts 和
EvaluationRun results，使已有 Observation 可以离线重判、换模型评分或按另一侧重点生成新报告。

### Playbook 路径（长期功能测试）

```text
Playbook + Target
    → AI Compiler
    → Script
    → Target SDK / Driver
    → Observation（Outcome + screenshots / video / logs / traces）
    → Unit → Dataset
    → EvaluationRun / Worksheet（Judge / Evaluation / Measurement）
    → Verdict + Report
```

AI 只参与编写期 / build-time 编译。生成的 Script 应进入被测产品仓库，经过 review 并随代码提交；运行时执行已确定的 Script，不临时调用 LLM 决定测试步骤。Script 应保留 Playbook 版本 / hash、Target、编译器与 SDK 版本等 provenance，以便发现漂移和重现失败。

同一 Playbook 可以生成 Web、Android、iOS 和 API 等多份 Script。共享的是用户目标与验收结果，不是一份跨平台的最低公分母脚本。

## 4. 测试边界

| 层级 | 意图锚点 | 执行边界 | 能覆盖 | 不能替代 |
|---|---|---|---|---|
| Web / App 功能测试 | Playbook 中的用户目标 | UI / 产品入口，可横跨多服务 | 前端 / 客户端代码、导航、交互和后端整体链路 | 平台差异下的其它客户端 |
| API 功能测试 | 同一 Playbook 中的用户结果 | 产品入口 API，可串联多步、多服务 | 业务规则与后端整合，通常比 UI Script 更快更稳定 | Web / App 客户端代码与交互 |
| 服务 API 契约测试 | API 契约与 Case | 单个服务的 HTTP / SSE / RPC 边界 | 服务对外语义和其内部完整链路 | 产品级多步用户功能 |
| unit 测试 | 实现代码 | 函数 / 类 / 模块 | 局部行为和边界分支 | 对外契约与真实集成 |

API 功能测试是功能测试的一种 Target 投影，不是服务 API 契约测试的别名。前者锚定用户结果，可编排多步甚至多服务；后者锚定单服务的对外契约。两者都值得在大规模改动后重跑，但只有 Web / App Script 能直接覆盖客户端代码。

## 5. Target SDK / Driver 边界

case-harness 长期为每类 Target 提供便于生成脚本和稳定执行的 SDK / Driver，至少覆盖：

- 会话、认证、前置数据和清理；
- 稳定等待、重试与超时，避免由脚本各自实现易 flaky 的调度逻辑；
- 平台动作和断言原语；
- screenshot、录屏、网络日志、设备日志、trace 等失败证据采集；
- 统一 Run / Verdict 产物和对齐键。

平台通用能力属于 case-harness；“创建笔记”、“邀请协作者”等产品域动作属于被测产品仓库。不为了表面复用而强迫 Web、Android、iOS 和 API 共享一套浅抽象；它们共享 Playbook / Run / Verdict 契约，各自持有会独立演进的 Driver。

Kubernetes 操作、资源状态等待和 Events 采集属于可被 e2e、perf 等多个视角复用的平台工具箱。工具箱只回答“如何操作和观察部署环境”，不拥有“破坏哪个实例、何时注入、怎样算恢复”等项目语义；这些仍由消费仓的 Case 与 Harness 决定。因此，同一个 Kubernetes Driver 可以被确定性恢复测试和容量、扩缩容观测共同使用，而不需要建立独立的 Kube Harness。

混沌工程工具是这一平台边界上的可选故障注入后端，而不是 case-harness 的 Case、编排或判定事实源：[Chaos Mesh](https://chaos-mesh.org/) 与 [ChaosBlade](https://chaosblade.io/) 适合 Kubernetes Pod、网络和资源故障，[Toxiproxy](https://github.com/Shopify/toxiproxy) 适合确定性的依赖网络故障，[AgentChaos](https://github.com/IntelligentDDS/AgentChaos) 则提供 LLM API 输出截断、字段遗漏和错误响应等 Agent 语义故障的分类与实现参考；[LitmusChaos](https://litmuschaos.io/) 已包含 Workflow、Probe 和 Result 等完整平台能力，接入时应避免与 CaseRun 和 Verdict 重复建模。只有出现至少两个真实后端后，才从具体 Driver 中收敛通用故障注入接口。

## 6. 判定与观测视角

同一 Case 或 Playbook Run 可以被多个视角消费：

| 视角 | 回答的问题 |
|---|---|
| e2e | 确定性契约或验收条件是否成立 |
| eval | 产出或行为质量是否达标 |
| perf | 延迟、吞吐与资源是否满足约束 |
| trace | 链路内部哪一层先反常 |
| trajectory | agent 的决策和行动过程是否合理 |

视角不等于多次独立发压。能复用一次执行的输出、trace 和行动轨迹时，应从同一 Run 生成多个判定与分析产物。

## 7. Owner 与依赖方向

- [`spec-case`](https://github.com/compforge/spec-case) 持有 Case，以及未来 Playbook 等稳定资产格式；资产实例通常与被测产品共存。
- case-harness 持有从资产到执行的运行边界：目标编译、Runner / Driver、Judge、Run 产物与 Verdict。
- 被测产品仓库持有自己的 Case / Playbook 实例、生成并 review 过的 Script，以及产品域操作封装。
- unit 测试依旧属于被测代码自身，不纳入 case-harness 的资产或运行模型。

依赖始终朝稳定方向流动：Script 依赖 Target SDK 和 Playbook 意图，Driver 实现依赖平台工具，但 Playbook 不依赖生成脚本的语言、测试框架或具体 UI 定位符。

## 8. 可验证交付

case-harness 只有在被测项目持续维护验证资产时才能产出可信证据。一个可验证交付的项目需要同时形成两段闭环：

```text
需求 / 外部行为变更 / 缺陷
    → Spec + Case / Playbook 随代码演进
    → review 与资产漂移检查
    → 指定 revision 部署到目标环境
    → 外部触发声明的验证集合
    → Run + Verdict
```

开发期由项目把稳定行为、回归场景和验收标准沉淀为版本化资产；部署后再由外部执行者针对确定的 revision、deployment 和 environment 将这些资产运行成证据。缺少前半段，一键验证只是在重复一套逐渐过时的测试；缺少后半段，Spec / Case 仍只是没有运行事实的声明。

这里的“可验证”不是项目对自身正确性的形式化证明，只表示某个明确版本在指定环境下通过了已声明的验证集合。Verdict 必须能够追溯到对应的资产版本、Target、环境和执行证据；`skipped` 或 `error` 不能被发布策略解释成已经验证成功。

Owner 分工保持明确：

- 被测项目拥有 Spec、Case / Playbook、判定标准和产品域适配；
- case-harness 拥有 Runner / Driver、Judge、Run 产物与 Verdict；
- 部署领域拥有环境、凭据、触发时机、审批和发布门禁。

CLI、API、Pipeline、Kubernetes Job 等只是外部触发同一验证能力的适配方式，不进入稳定内核。服务本身不需要暴露一个运行测试或发压的业务接口；完整 Perf 等高影响验证必须由部署策略限制在合适环境和明确授权下运行。

## 9. 当前与长期边界

| 能力 | 状态 |
|---|---|
| Case / CaseSet 资产与统一 Verdict | 已实现，持续收敛 |
| API e2e / eval / perf / trace / trajectory | 已有不同成熟度的实现 |
| Playbook 资产格式 | 尚未实现，等第一个真实功能测试消费方校准 |
| Playbook → Script 的 AI 编译 | 尚未实现；长期为 authoring-time 工具，不进运行链路 |
| Web / Android / iOS / 产品 API Target SDK | 尚未实现；待真实 Playbook 推动边界 |

未实现能力只在本文确定长期概念和依赖方向，不预建空 SDK、统一 Driver 接口或无消费方的 schema。

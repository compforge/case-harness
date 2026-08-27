# case-harness 内核

> 本文只描述所有 Harness 共同遵守的稳定语义、数据边界和依赖方向。领域执行、分组、节点和切片等
> 概念由各自设计文档持有。

## 1. 理念

case-harness 让稳定的测试意图能够持续积累、重复执行，并把不同质量视角的结果收敛为可追溯产物。
e2e、eval、perf、trace 和 trajectory 可以拥有不同执行模型，但共同遵守从测试意图、观察事实到
评估结果的语义边界。

测试边界与判定视角是两根正交的轴：被测入口回答“从哪里验证”，Harness 回答“从哪个角度观察和
判定”。一次执行已经产生的 response、outcome、trace 或 trajectory 应尽量复用，不为了增加判定
视角而重复触发被测系统。

## 2. 核心概念

| 概念 | 语义 |
|---|---|
| **Case** | 可重用的结构化测试意图，具有稳定 `case_id`；canonical 资产由 spec-case 持有，可被多个 Harness 消费。 |
| **Observation** | 执行或采集后实际观察到的领域事实；必须保留来源 identity 与 provenance，不包含质量判断。 |
| **Unit** | Harness 声明的评估单元，也是 Worksheet 一行所代表的基本粒度；其数据来源是对齐后的 Case 与一个或多个 Observation。Unit 拥有自己的稳定 key，唯一确定一行；Observation 尚未产生或失败时，该行可以保留 pending / failed 状态。 |
| **Annotation** | 运行当前评估前已经存在的人工、外部系统或模型监督信息，例如 label、reference 和复核结论；按 Unit 对齐并保留 producer 与 provenance。 |
| **Dataset** | 一组可复用、版本化的 Unit facts，固定 Case、Observation、Annotation 及其来源关系，不包含某次 EvaluationRun 的 Finding、Evaluation 或 Measurement。相同 Dataset 可以按不同侧重点反复评估。 |
| **EvaluationRun** | 对一个确定 Dataset version 执行一组 Detector、Evaluator、Measurer 与可选 Policy 的运行实例；它记录实际组件的 spec、模型、规则、版本和配置，并拥有 run identity、执行健康与对应 Worksheet。 |
| **Finding** | `detect` 从 Unit 中识别出的模式或异常，带有证据、严重度和原因假设，但不直接给出质量 verdict。 |
| **Evaluation** | Judge / Evaluator 根据契约对 Unit 作出的质量判断，包括状态、verdict、score 和 explanation；使用确定性规则还是 LLM 是实现方式，不改变其语义。 |
| **Measurement** | 从 Unit 直接提取的 token、耗时、调用量和资源用量等中性事实，不携带质量 verdict。 |
| **Worksheet** | 一个 EvaluationRun 的行式工作模型：以 Dataset Unit 为行，保存 seed 事实以及本次追加的 Finding、Evaluation、Measurement 和 cell state。它是生成报告和聚合指标的事实输入，不等于某一种物理文件格式。 |
| **Run** | 一次真实执行的生命周期和产物边界，记录输入版本、环境、输出、证据和对齐 identity。 |
| **Report** | Worksheet 的下游投影；JSON 面向机器，HTML 面向人，不重新执行或评估源数据。 |
| **Verdict** | 对一次 Run 的可机器消费判定。人、CI 和 agent 开发循环都通过它判断是否通过、为何失败，以及下一步应读哪些证据。 |

这些名字定义共同语义，不要求不同语言或 Harness 共享同一组公开 class、schema 或 API。

## 3. 共同数据闭环

```text
Case
  + execution / collection
  → Observation
  → Unit（Case + Observation + Annotation）
  → versioned Dataset

Dataset + Detectors / Evaluators / Measurers / optional Policy
  → EvaluationRun
      detect   → Finding
      evaluate → Evaluation
      measure  → Measurement
  → Worksheet（Unit + Finding + Evaluation + Measurement）
  → Metric / Verdict / Report
```

### Dataset 与反复评估

所有 Harness 都按同一组顶层概念组织数据：先基于 Case 得到真实 Observation，以两者为数据来源建立
评估 Unit，再将一组 Unit 固定为可复用 Dataset。每次运行选择的 Detector、确定性规则、LLM Judge、Measurer
与可选 Policy 直接定义评估侧重点；每次 EvaluationRun 形成自己的 Worksheet 和 Report。

Worksheet 的一行始终等于 Unit seed 加上本次 Finding、Evaluation 与 Measurement；聚合、透视和报告都是这张
表的下游操作。

Dataset 和 Worksheet 使用相同 Unit grain。一个 Harness 存在多种基本粒度时，应形成多个明确 grain
的 Dataset / Worksheet，不能把不同层级的行混进一张无从解释的大表。具体 grain 和 key 由领域文档
定义。

一个 Case 可以产生一个或多个 Observation；直接产出的 response、outcome 与经过采集、转换后形成的
trace、trajectory 在这一层没有本质差别。Observation 必须携带足够的来源 identity 和 provenance，
使其能够稳定对齐原始 Case、Run 和中间产物，不能依赖文件名或报告渲染阶段猜测关系。Case 提供输入、
预期、facets 和 ground truth 等稳定 seed，Observation 提供系统实际做了什么；Unit 在 Harness 声明的
grain 上将两者形成独立、可寻址的评估单元。

Dataset 固定 Unit facts 和已有 Annotation；EvaluationRun 只向 Worksheet 同行追加不同语义的列族：

- **Annotation**：人工、外部系统或模型预先提供的 label、reference 与复核信息；保留 producer 和
  provenance。数据由 LLM 生成并不会自动使它成为 Evaluation，语义取决于它是否在表达监督信息。
- **Finding**：Detector 在本次运行中发现的模式或异常；保存证据、严重度和可能原因，
  但本身不表示通过或失败。
- **Evaluation**：Judge / Evaluator 根据契约对 Unit 作出的质量判断和分数；即使内部调用
  LLM，它仍属于 Evaluation。
- **Measurement**：从 Unit 直接提取的 token、耗时、调用量和资源用量等中性事实。

`detect / evaluate / measure` 是并列的处理职责，对应产物 Finding、Evaluation 与 Measurement 是同一
Worksheet 上并列的结果列族；Policy 消费这些结果并生成
Verdict。Finding 不能绕过显式 Policy 自动变成门禁结论。

Case、Observation 或 Annotation 改变会形成新的 Dataset version；只更换 Detector、Evaluator、Measurer、模型、
规则、成本口径、Policy 或分析侧重点，应创建新的 EvaluationRun 并复用原 Dataset。EvaluationRun
必须记录实际运行的组件 spec 与配置，以支持复现和比较。Metric
是对已填充 Worksheet 按 run 或领域维度聚合后的结果，不是另一份与行数据脱节
的事实源。报告层只做 join、pivot、aggregate 和 render，不重新执行 Case、不重新读取远端 Source，
也不重新运行 Judge。内部 JSON 保存无损、可恢复的数据，`verdict.json` 是统一机器判定投影，HTML
是面向人的 UI 投影；需要 CSV 等格式时也从同一 Worksheet 派生。

所有 Harness 必须能映射到这套共同语义，但不要求共享同一个 `Dataset` / `Unit` / `Worksheet` 类或
schema。各领域拥有自己的 Unit grain、强类型 key、列类型、调度和聚合语义；物理实现也可以把
Dataset build、Observation production 和 Evaluation 融合在一个带 cell state 的 Worksheet/checkpoint
中，只要事实列与本次评估列可分离，并能复用 Observation 重新评估。

## 4. 判定与观测视角

同一 Case 或 Run 可以被多个视角消费：

| 视角 | 回答的问题 |
|---|---|
| e2e | 确定性契约或验收条件是否成立 |
| eval | 产出或行为质量是否达标 |
| perf | 延迟、吞吐与资源是否满足约束 |
| trace | 链路内部哪一层先反常 |
| trajectory | agent 的决策和行动过程是否合理 |

视角不等于多次独立发压。能复用一次执行的输出、trace 和行动轨迹时，应从同一 Run 生成多个判定与分析产物。

## 5. Owner 与依赖方向

- [`spec-case`](https://github.com/compforge/spec-case) 持有 canonical Case 等稳定测试资产格式。
- case-harness 持有执行机制、领域 Harness、Run 产物、报告基础设施与 Verdict 契约。
- 被测项目持有资产实例、业务适配、环境相关过程和验收标准。
- 部署领域持有目标环境、凭据、触发时机、审批与发布策略。
- `harness_common` 只承载中立能力，不能反向拥有 Trajectory、Trace、Perf 等领域模型。

依赖始终朝稳定方向流动：领域 Harness 可以依赖共同契约，共同层不依赖某个领域的 Unit、调度或聚合
模型。CLI、API、Pipeline 和 Job 只是触发适配，不进入稳定内核。

## 6. 可验证交付

case-harness 只有在被测项目持续维护验证资产时才能产出可信证据。一个可验证交付的项目需要同时形成两段闭环：

```text
需求 / 外部行为变更 / 缺陷
    → Spec + Case 随代码演进
    → review 与资产漂移检查
    → 指定 revision 部署到目标环境
    → 外部触发声明的验证集合
    → Run + Verdict
```

开发期由项目把稳定行为、回归场景和验收标准沉淀为版本化资产；部署后再由外部执行者针对确定的 revision、deployment 和 environment 将这些资产运行成证据。缺少前半段，一键验证只是在重复一套逐渐过时的测试；缺少后半段，Spec / Case 仍只是没有运行事实的声明。

这里的“可验证”不是项目对自身正确性的形式化证明，只表示某个明确版本在指定环境下执行过已声明的
验证集合。Verdict 必须能够追溯到资产版本、目标 revision、环境和执行证据；`skipped` 或 `error`
不能被发布策略解释为已经验证成功。

## References

- Canonical Case 与 CaseRun：[`case-unification.md`](case-unification.md)
- 跨 Harness 环境操作与观测工具箱：[`toolbox.md`](toolbox.md)
- e2e、Playbook 与 Target：[`e2e-harness.md`](e2e-harness.md)
- Quality Harness 的跨领域编排：[`quality-harness.md`](quality-harness.md)
- Trace 领域模型：[`trace-harness.md`](trace-harness.md)
- Trajectory 领域模型：[`trajectory-harness.md`](trajectory-harness.md)
- Perf 跨语言契约：[`../spec/perf-contract.md`](../spec/perf-contract.md)
- Eval 领域约定：[`../python/eval_harness/AGENTS.md`](../python/eval_harness/AGENTS.md)

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
| **Case** | 一个可重用的结构化测试输入，具有稳定 `case_id`。它适合表达一次 API / agent 输入，可被 e2e、eval、perf 等不同视角消费。 |
| **Playbook** | 用自然语言表达的产品功能测试剧本：用户目标、前置条件、有序动作、关键检查点和最终验收结果。它与 Web / Android / iOS / API 等执行目标解耦。 |
| **Script** | Playbook 针对某个 Target 编译出的可执行代码。它是可 review、可重放、可再生成的派生产物，不是功能需求的事实源。 |
| **Target** | 脚本真正操作的系统边界，例如 Web、Android、iOS、产品 API 或单服务 API。Target 决定 Script 使用的 SDK / Driver 和可观测证据。 |
| **Run** | 一次真实执行的生命周期和产物边界，记录输入版本、Target、环境、输出、证据和对齐键。Experiment / Arm / Trial 是在 Run 之上组织对照的编排语义。 |
| **Verdict** | 对一次 Run 的可机器消费判定。人、CI 和 agent 开发循环都通过它判断是否通过、为何失败，以及下一步应读哪些证据。 |

### 为什么叫 Playbook，不叫 Scenario

`Scenario` 通常表示一个具体条件下的单个示例，容易与已有 Case 概念重叠。`Playbook` 更强调为了达成某个用户目标而执行的有序动作、检查点与清理流程，也更适合作为多个 Target Script 的稳定源。

当前不预先建立“Playbook 包含多个 Scenario”的层级。只有真实功能测试出现需要独立标识、单独编排的多个变体时，Scenario 才值得成为下一层概念。

## 3. 主流程

### Case 路径（当前主路径）

```text
Case → Runner / Driver → Outcome + observations → Judge → Verdict
```

Case 是可直接消费的结构化数据。不同 harness 可以对同一次执行做确定性断言、效果评估、容量观测或链路归因，不必为每个视角重复发起请求。

### Playbook 路径（长期功能测试）

```text
Playbook + Target
    → AI Compiler
    → Script
    → Target SDK / Driver
    → Outcome + screenshots / video / logs / traces
    → Judge
    → Verdict
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

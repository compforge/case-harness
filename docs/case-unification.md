# Case 统一：单一 canonical `common.Case` + 多编写前端（判定即数据）

> 状态：**提案（未落代码）**。核心方向已定——**判定即数据**（e2e 走结构化 `assert`）、`common.Case` 为唯一类型；
> e2e 管线的几处承重决策已拍（见 §3.8），本文从**设计合理性 / 长期目标**出发，不计兼容与工作量。
> 范围：跨 `e2e_harness` / `eval_harness` / `perf_harness` 三个 SDK 的 **输入侧 case 表示**。
> canonical schema 见 [`../spec/case-schema.yaml`](../spec/case-schema.yaml)；输出侧对称收口见 [`../spec/verdict-schema.yaml`](../spec/verdict-schema.yaml)（已落地）。

## 1. 理念 / 概念

### 1.1 问题：现在有三套平行的 case 表示

| 表示 | 在哪 | 形态 | 服务谁 |
|---|---|---|---|
| `common.Case` | `common/case.py` | data，`case.yaml` 加载 | perf（!96 已采用）；canonical 目标 |
| `eval_harness.EvalCase` | `eval_harness/model/evalset.py` | pydantic，`evalset.yaml` | eval-suite（质量评测）|
| `e2e_harness.api.contract.Case` | `e2e_harness/api/contract.py` | dataclass，`@case`/`+e2e:case` 注解 | eval-api（接口契约）|

`case-schema.yaml` 已经把目标写死——**`common.Case` 是唯一 case 类型，三面各自直接读它，不存在 per-harness Case 类**。
但实现停在平行态：eval 用自己的 `EvalCase`、e2e 用自己的 `contract.Case`。本文讲怎么收口。

### 1.2 两根正交轴

case 有**两根互不相关的轴**，别混成一根：

```
                                face 轴  (judge.<面>，按面分区、全部可选、缺面=只观测)
                                  e2e   |   eval   |   perf
  authoring 轴 (case 谁写、存哪)：
   ├─ case.yaml          (data-first)    外部语料 / 数据集 / 跨 SUT 复用、可分享、累积
   └─ @case / +e2e:case  (code-first)    贴着 handler、AST 静态发现、case_hash 漂移检测
                          ↘                 ↙
                     都归一到 common.Case（唯一类型；下游 engine/judge/report 只认它）
```

- **face 轴**已在 schema 建模（`judge.{e2e,eval,perf}`，公共段 `id/input/facets/requires` 三面共用）。
- **authoring 轴**是要补的认知：`case.yaml` 和代码注解是**两个编写前端**，不是两种 case。

### 1.3 两条承重结论

1. **统一类型，不统一存储。** `common.Case` 是唯一 canonical 类型（统一消费）；`case.yaml` 与代码注解是两个原生编写前端，各保留体验（不统一存储）。
2. **判定即数据。** 确定性判定（e2e 的 `assert`、perf 的 SLO、eval 的评分契约）**是 case 数据的一部分，不是人写进测试体的代码**。这是 e2e 收口的承重原则，理由见 §3.3。

## 2. 流程

```
[数据路径]
  case.yaml ───────────────────────────────────────▶ load_caseset() ─┐
                                                                       │
[代码路径]                                                             ├─▶ [结构化 common.Case]
  NL marker ─▶ discover(AST 抽 NL) ─▶ build-time LLM 编译 ─▶ case.yaml ────┘            │
                                     (NL→结构化, 人 review,                          │
                                      提交且与 handler 同处)                          ▼
                                                            engine（执行 input + 跑 judge.<面>，run 路径零 LLM）
                                                                                     │
                                              一份 case 一次执行；每个声明 judge.<面> 的面各产一行 verdict
                                                                                     ▼
                                                                    report（engine 自带；pytest 仅可选适配器）
```

- **代码路径的编译产物也是 `case.yaml`**——一旦编译提交，两条路在 `case.yaml → common.Case → engine` 完全汇合。下游不关心来源。
- 下游（engine / judge / report）**只见结构化 `common.Case`**。

## 3. 关键设计

### 3.1 为什么是唯一 canonical 类型（而非 per-harness）

单一事实来源 + 跨面复用：同一个 stimulus 想跨面跑（一条 query 既判质量、又判接口不报错、又测延迟）时，必须有共享的 case 身份。`case-schema.yaml` 已为此设计：公共段三面共用，`judge.<面>` 按面分区可选，缺面即"只观测不判"——这正是 per-SUT 跨面复用的载体。

### 3.2 为什么保留两个编写前端（不塌缩存储）

- **代码注解的价值是 co-location + 漂移检测**：case 贴着它断言的 handler，改 handler 就看见并更新它。语料 case 的价值是**可分享数据集**（RAG 题集、压测输入），`case.yaml` 是它的家。
- 选哪个前端，看 case 身份**绑在一段代码上**还是**绑在一个数据集上**。
- 注意：代码路径的编译产物 `case.yaml` **与 handler 同处、不入中央目录**——既钉住 LLM 的非确定输出（可 review、可 hash），又不丢 co-location。

### 3.3 判定即数据（e2e 收口的承重原则）

确定性判定是 case 数据，不是人写进测试体的代码。针对 e2e 现在的 NL `expect/forbid` 老模型，四条理由：

- **确定性**：e2e 是确定性面；NL→LLM 在**build-time就非确定**（同句 NL 不同模型编出不同断言），毁掉 e2e 的意义。结构化 `assert` 天生确定。
- **case 自洽 / 漂移闭合**：结构化下 `case.yaml` 完整描述检查，`case_hash` 盖住**真实断言**；NL+人写 body 下，真断言逃逸到 case 外的测试代码里，hash 抓不到漂移（scaffold 的"框架区 vs 人写区"切分就是在补这个漏）。
- **跨语言**：一份 `assert:[{path,op,value}]`，Go/Python 两个 runner 同样执行；NL+编译则每语言各 scaffold 一套、各自漂。
- **三面一致**：perf 早已是结构化 `slo:[{metric,op,value}]`、eval 是结构化契约字段——只有 e2e 的 NL `expect/forbid` 是历史孤儿。

**NL 不删，往左挪**：NL 留在 marker（人写意图的前端），LLM 在**build-time**编译成结构化 `judge.e2e.assert` 并提交（人 review）；run 路径零 LLM、零人写断言。你伸手够 NL 表达"语义/模糊"判定时，那其实是 **eval 面（非确定）**的活——强制 e2e 结构化反而把 e2e/eval 边界钉清，是收益不是限制。

### 3.4 e2e 的 0→1 组件（从零写会怎么搭，不从"老模块退化成什么"想）

**共享脊柱（common，schema 锚、跨语言）**：`Case` · `Verdict` · `CaseSet`+loader · **协议适配器**（HTTP/SSE/RPC：一个请求"怎么发"）。

**e2e 面四段：**

| 段 | 组件 | 时机 |
|---|---|---|
| 编写 | NL marker（贴 handler）+ `case.yaml`（数据），都属 `marker/` 前端 | — |
| 编译 | `casegen`：AST 抽 NL → LLM 编译成结构化 `Case` → 提交 co-located `case.yaml` + 漂移 check | **build-time** |
| 运行 | 通用 `engine`：读 `Case` → 适配器发 `input` → 收 → 跑 `judge.e2e.assert` → `Verdict` | **run-time**（零 LLM、零人写断言）|
| 报告 | over `Verdict`（md/html）；`pytest` 仅可选适配器，非地基 | — |

**这套里根本不存在**（不是退化，是没有）：

- ❌ **scaffold**——无 per-case body 要生成，engine 直接吃 `Case` 跑。
- ❌ **`BaseCase/AgentCase/RPCCase` 测试类**——本质 re-home 成**协议适配器**（共享发射策略，不是每 case 一个类）+ 通用 engine。
- ❌ **test 文件里的 meta_block**——漂移落 `case.yaml` 的 `case_hash`。

**数据，不是代码**：多步 case = `steps:[{fire,assert}]` 序列；流式 agent = SSE 适配器 + `assert` 进 `events[]`；真正任意逻辑（极少）才落一个 code hook（例外，非常态基类）。

### 3.5 收口的两半（同一个动作）

**半 B — `marker → 结构化 common.Case`（code-case）。**

| marker (NL) | → 结构化 common.Case |
|---|---|
| `@case` 的 NL `input` | LLM 编译 → 结构化 `input`（请求 dict）|
| NL `expect` / `forbid` | LLM 编译 → `judge.e2e.assert: [{path,op,value}]` |
| `@spec`（NL 约束块）| 编译上下文；并入 `case_hash` 覆盖范围以保留意图漂移 |
| `group` | 文件组织属性，留 discovery 层 |
| `endpoint` / `source_module` | **不进 case 本体**，留 discovery wrapper 回指 |

`case_hash` 收口到 `common.case_hash`（over 结构化 case，含真实 `assert`）；`desc` 降为装饰（不入 hash）。

**半 A — `EvalCase → common.Case`（data-case，重头）。** `EvalCase` 横跨 9 个文件（config / ingest / worksheet / reconcile / experiment / produce / model），字段 `query / expected_behavior / ground_truth / dimensions / evidence_sources / candidate_sources` + 校验器 + 序列化。映射：

| EvalCase | → common.Case |
|---|---|
| `query` | `input`（schemaless dict，装 query）|
| `dimensions` | `facets` |
| `expected_behavior` / `ground_truth` / `evidence_sources` / `candidate_sources` | `judge["eval"]`（eval 面自治字段）|

风险：`EvalCase` 穿过 worksheet/checkpoint/reconcile 的数据流，动核心模型有回归面；必须分步、每步可回退。

### 3.6 边界：共享单位是「同一 SUT 跨面」，不是「全局 case.yaml 跨产品」

- sut-a-server（**eval-suite + eval-api 两个活 face、同一 SUT**）是一个共享域——一条代表性 query 喂两面，统一立刻有回报。
- **chat-server/eval-perf 是另一个 SUT**，请求形状不同，自成一域；别想一份 `case.yaml` 同喂两个不同 SUT。
- 重叠是**部分**的：eval-api 价值多在错误/边界 case，eval-suite 在带 ground-truth 的质量 case；共享的是"代表性 valid query"这个核 + 各面扩展。

### 3.7 建议分步（每步独立 MR、可回退）

1. **e2e 面（半 B）**：建 `marker/` 前端 + `casegen` 编译器（NL→结构化 `Case`，build-time）+ 通用 `engine`（吃 `Case` 跑 `assert`，无 scaffold/BaseCase）+ drift 落 `case_hash`。
2. **eval 落点：SUT-A beachhead（半 A）**：`eval_harness` 内把 `EvalCase` 重构为 `common.Case` 投影，分批迁 9 文件；`evalset.yaml → case.yaml` 随后。
3. **消费侧对齐**：eval-api / eval-suite 两面读同一 sut-a-server case 集，验证一条 query 跨两面跑通。
4. **（暂不做）perf** 不掺和 SUT-A 的 case 集——它是 chat-server 的 SUT。

### 3.8 决策 / 待决

**已拍（只论设计合理性，不计兼容与工作量）：**

- ✅ `judge.e2e` = **结构化 `assert`**（非 NL 映射）。
- ✅ marker = **NL + build-time LLM 编译**成结构化（保人体工学；LLM 当助手、不在 run 路径）。
- ✅ pytest = **可选适配器，非地基**（engine 自带 runner / 发现 / verdict / report；要 CI/IDE familiarity 才 bolt pytest）。
- ✅ 流式 / 多步 **数据化**：`assert` 进 `events[]`（计数/序列 op）、多步用 `steps:` 序列；真正任意逻辑落一个 code hook（例外，非常态基类）。
- ✅ `case_hash` 收口 `common.case_hash`；`desc` 降装饰。
- ✅ **eval-api 先不管**（版本锁着，迁移作后续债）。

**仍待决：**

- `assert` 词汇的扩展边界（`events[]` 路径、有序/序列断言）做到哪算够。
- ~~build-time LLM 编译的工程形态~~ → 已定，见 [`casegen.md`](casegen.md)。
- **独立的债**：`chat-server/eval-perf` inline `cases[].weight` 会被 !96 迁移校验拒（锁 0.0.74 暂安全、升级即炸）——与本提案无关，需另还。

## References

- canonical case schema：[`../spec/case-schema.yaml`](../spec/case-schema.yaml)
- 输出侧对称收口：[`../spec/verdict-schema.yaml`](../spec/verdict-schema.yaml)
- e2e_harness（注解/contract/scaffold）现状设计：[`design.md`](design.md)、[`../go/AGENTS.md`](../go/AGENTS.md)
- casegen（NL marker → 结构化 case 的 build-time 编译器，§3.4 那步的展开）：[`casegen.md`](casegen.md)
- Overlay（mix/weights 抽象，本轮已落地的相邻收口）：`common/overlay.py`

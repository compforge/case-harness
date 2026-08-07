# e2e-harness 约定

## Case 规范（canonical case）

case 是**可积累、可分享**的资产：同一份 case，e2e 看对错、eval 看效果、perf 看压力下表现，一次执行多面观测；而且能**把它给别人、或拿别人的 `case.yaml` 来驱动你自己的 e2e/eval/perf**（像一份 conformance / benchmark 语料）。要做到，必须守住下面的硬规则（文件形状见 [`case-schema.yaml`](case-schema.yaml)；唯一中立模型 + load/validate/case_hash 落在 `python/common/case.py`，与 `common/verdict.py` 输出契约对称——判定面 `judge.<面>` 的 key = `common.Face`，与 verdict 的 `harness` 共用，`case.id` == `verdict.case_id`）：

1. **id 不可变、集内唯一**。id 是跨 run / 跨 harness 对齐结果的主键（输入 `case.id` == 输出 `verdict.case_id`）；语义变了换新 id，不复用旧 id。意图漂移检测用 `case_hash`（`common/case.py`）。
2. **case 无环境**。不写 base_url / token / 模型名——环境归 experiment config。同一 case 必须能打到任意环境/SUT。
3. **case 无实验参数**。混流权重、并发、重复次数归 experiment；case 只描述单次请求长什么样。
4. **判定按面分区（`judge.e2e/eval/perf`）且全部可选**。缺某面判定 = 该面只观测不判定（"观测面 ⟂ 判定面"）。公共段（id/input/facets/requires）演进走 spec/，判定段字段各 harness 自治。
5. **facets 必须有词表 schema**。约束 values + ordered + `open` 逃生舱；自由字符串列会腐烂。
6. **case 声明依赖，不执行准备**。case 用 `requires` 按名引用素材；素材本体（`sources`）与 case 同文件积累、进 git；provision（上传/建库）、复用（key = 素材内容 hash）、清理（复用制下退化为按 key 的 GC）都是 experiment 运行时的事。
7. **case 是 git 里的平文件**。yaml 进消费方仓库（`cases/<domain>/*.yaml`），可 diff、可 round-trip；不进 DB。框架仓库只放 schema + mock case。
8. **唯一 `common.Case`，各家行为直接消费**。canonical case 是**唯一的 case 类型**（`common/case.py`）；三面（含 e2e）的**行为各自直接读它**——runner/solver/workload 读 `input`、报告读 `facets`、各面读自己那段 `judge.<面>`——**不存在 per-harness Case 类、不做 case 类的投影**。这和输出侧对称：case 是被各家行为消费的纯数据，正如 verdict 是各家行为产出的纯数据。

> e2e 的 `@case` 注解（贴 handler 的 5 字段意图 → AI scaffold 生成 pytest）是 canonical case 的一种 **co-located 编写前端**：它产出 / 按 id 链接 canonical case，便于"贴着代码写 + 改 handler 时 case_hash 报漂移"；e2e 同样可直接吃 `case.yaml`。**编写位置不同（yaml / 注解 / AI），case 定义统一。**

## 核心概念

| 概念 | 职责 |
|------|------|
| **Case** | 声明测试意图：输入 + 期望 |
| **Runner** | 协议适配：将 input 变成请求，收集响应 → Outcome |
| **Outcome** | Runner 和 Judge 之间的标准化契约 |
| **Judge** | 对 Outcome 做判定：硬断言（assert）或软评分（metric） |
| **Pipeline** | 编排：case × runner × judge 的组合 |

## 生命周期

所有 case 遵循四阶段：

```
prepare → trigger → judge → clean
```

- `prepare`：创建前置资源（可选）
- `trigger`：Runner 发请求收响应，产出 Outcome
- `judge`：Assert（硬 pass/fail）和/或 Metric（软评分 0~1）
- `clean`：best-effort 清理，永不 fail 测试

## Outcome 结构

Runner 输出、Judge 输入的统一中间表示：

```yaml
status_code: int
body: dict | null          # JSON 解析后
headers: dict
duration_ms: int
metadata: dict             # runner 特有的提取物（trace_id, message_id 等）
raw: bytes                 # 原始响应
```

Outcome 可序列化，支持阶段可恢复（保存 outcome → 重跑 judge 不重跑 runner）。

## 文件命名

| 语言 | 测试文件 | 隔离机制 |
|------|---------|---------|
| Go | `*_e2e_test.go` | `//go:build e2e` |
| Python | `test_*_e2e.py` | `@pytest.mark.e2e` 或 conftest 注册 |

## 目录结构（服务接入侧）

测试目录 mirror 服务 API 结构：

```
<service>/tests/e2e/
├── config.yaml            # 服务级配置
├── cases/                 # YAML case 定义（可选）
├── <domain>/
│   ├── test_xxx_e2e.py    # Python
│   └── xxx_e2e_test.go    # Go
└── conftest.py            # Python fixtures
```

## Config 格式

```yaml
service:
  name: <service-name>
  base_url: ${ENV_VAR:-default}

auth:
  tenant_id: ${TENANT_ID}
  user_id: ${USER_ID}

runtime:
  http_timeout_s: 120
  poll_interval_ms: 500
  poll_timeout_s: 60

profile: ${ENV_PROFILE:-full}

custom:                    # 服务自定义扩展区，框架透传
  key: value
```

插值规则：
- `${VAR}` — 必须存在
- `${VAR:-default}` — 缺失时用 default

## Runner 类型

| Runner | 协议 | sync/async | 状态 |
|--------|------|-----------|------|
| `JSONRunner` | HTTP JSON | sync | 已实现 |
| `AsyncJSONRunner` | HTTP JSON | async | 已实现 |
| `SSERunner` | HTTP SSE | sync | 已实现 |
| `AsyncSSERunner` | HTTP SSE | async | 已实现 |
| `WebSocketRunner` | WebSocket | - | 计划中 |

所有 runner 产出相同的 Outcome 结构（SSE events 进 `metadata['events']`），judge 层无需关心协议差异。

## Judge 类型

| 类型 | 适用 | 输入 | 输出 |
|------|------|------|------|
| `AssertJudge` 方法 | 硬断言 | Outcome | pass / 抛 AssertionError |
| `OutcomeMetric` 子类 | 软评分（Outcome） | Outcome | MetricResult (0~1) |
| `BaseLLMJudge` 子类 | LLM-as-judge | EvalSample | MetricResult (async) |
| 同步 metric 模块 | 关键词 / 模板匹配 | EvalSample | MetricResult |

四类都收敛到 `MetricResult(name, score, judgement)`。Assert 和 Metric 可在同一 case 并存：assert 全过 + metric 全达标 → case pass。

## 使用模式（三类 harness）

- **e2e（API 测试）**: pytest 驱动 + `BaseCase` 三段式 + sync runner / AssertJudge / OutcomeMetric。
- **eval（效果测试）**: `EvalEngine` 驱动大表 + reconciler 填表，per-case async runner + builder + metric set。
- **perf（压力测试）**: `Engine` 把资源档 × 负载档解析为 Arm，逐 Trial 采样并按 Window 聚合，出容量与资源画像。

三者**互不 import、不抽公共依赖**（耦合成本 > 省下的重复）：e2e/eval 各自复制一小撮 L2 原语
（Outcome 形状 / runner / SSEParser / build_auth_headers），perf 自带 httpx 发压栈。唯一例外是
业务无关的 `report_kit`（eval/perf 共用）。一致性落在 `spec/` 的**数据格式**，不落在共享代码。

## Run 产物与 verdict 出口（跨 harness）

四类 harness 的运行产物布局对齐到同一骨架，让消费方（devloop 等）"读 verdict 自纠偏"时
一个 glob + 一份 schema 全收：

```
runs/<scope>/<run-id>/
├── verdict.json        # 统一判定出口（必产）—— schema 见 verdict-schema.yaml
└── <富产物>            # 各 harness 自有：results.csv / run.json / junit.xml / report/ …
```

- **scope**：harness 中立的运行单元名（run 目录第一段）。`eval`/`perf`/`trace` = experiment 名；
  `e2e` = 套件/服务名（e2e 无 experiment 这一对照轴，不为它发明一个）。
- **run-id**：scope 内一次 run 的唯一标识，派生各 harness 自治，但语义分两类：
  perf/e2e 用**时间戳**（每次 run 留一份历史，累积不覆盖）；eval 用 **`experiment_hash`**
  （同配置 rerun 落同一 run 目录、原地 resume——内容寻址的复用 namespace，而非历史快照）。
  两类都落 `runs/<scope>/<run-id>/`，消费方一律 glob `runs/**/verdict.json`。
  （eval 早期是扁平 `runs/<exp>/`，已对齐补上 run-id 层。）
- **verdict.json**：每个 run 目录必产一份；只承载"判定结论 + 对齐用最小结构"，富产物用
  `artifact_paths` 指过去，不复制内容。两类判定单元分开：per-case 判定走 `cases[]`（对齐键
  `case_id`，与「Case 规范」第 1 条同一主键），run 级断言门走 `checks[]`（perf SLO 是首个实例）。
  wire 只存这两份事实 + run rollup，**不存派生计数**——"多少 pass/fail"消费方读时自己 fold
  `cases[]`/`checks[]`（perf 无 per-case 行，结论落 `checks[]`）。字段见 [`verdict-schema.yaml`](verdict-schema.yaml)。

各 harness 的 verdict 投影落点（M1 实现，薄投影，不新建判定能力）：

| harness | verdict 投影落点 | 来源 |
|---------|------------------|------|
| e2e | `e2e_harness/api/verdict.py`（纯投影）+ `pytest_plugin.py`（conftest opt-in，钩 `pytest_runtest_logreport` 等聚合落盘）；pytest 仍驱动 | 现成 PASS/FAIL/ERROR 三态 |
| eval | `eval_harness/verdict.py`，`engine.run_experiment` 收尾调用 `write_verdict()` | `row_overall`（weighted）+ per-cell state |
| perf | `perf_harness/verdict.py`，`report.write_run` 收尾调用 `write_verdict()` | 每条 SLO check → `checks[]`；run status 按 per-check rollup，cooldown skip 失败关闭；**不取 `run.passed`** |
| trace | `trace_harness/verdict.py`，`corpus.experiment.run_experiment` 收尾调用 `write_verdict()` | experiment 显式声明的 `gates:`（对三表/算子结果的断言）→ `checks[]`；**Finding 是发现不是判定**、永不直接变 verdict；无 gates → `skipped`（同 perf 记录门原则） |

> status 语义：e2e/perf 有 pass/fail/error/skipped；eval **无 fail**（质量不判对错）——status 表"执行是否完成"（pass/error/skipped），质量信号走 `score`（run 级 weighted overall）。trace 与 perf 同型（判定单元是 run 级 check 而非 case），区别在判定对象：perf 断言压测聚合指标，trace 断言遥测分析产物（错误签名/离群/Finding 计数）。各家 error 优先于 fail：判不了 → 结果不可信 → 先暴露。
> perf 尤其要分清两个门：`run.passed` 是**运行门**（CLI 退出码 / `abort_on_fail` / `strict_slo` 宽松），默认放过普通 skip；`verdict.status` 是**记录门**，按 per-check 状态 rollup——SLO 声明了却全 skip（或没声明 SLO）→ `skipped` 而非 `pass`。cooldown 用于证明恢复，skip 在两个门都失败关闭。

## 对齐键（跨平面 join 的前提，各 harness 迭代必守）

一个执行波次（一批 case 主动驱动 / nightly）落下四个数据平面：verdict（对错）/ metrics
（延迟资源）/ traces（链路）/ findings（判读）。devloop 消费与数据挖掘（顶层 AGENTS.md
「愿景」）都靠对齐键把平面 join 起来——单平面数字不可行动（"fail 23 个"不知为何、
"churn 率 20%"不知伤不伤），join 后才出可行动结论（"fail 的 23 个里 18 个命中 tool_churn
→ 改该 tool 的 desc"）。四组键，**迭代时不得破坏，新增产物/列时优先携带**：

- **case_id**：输入 `case.id` == 输出 `verdict.case_id`（「Case 规范」第 1 条主键）——
  case ↔ 判定的对齐，也是跨 harness 按题对齐的主键。
- **arm_id**：Experiment 内命名配置的对齐键。一个 case 在多个 Arm 上执行时，`case_id`
  不变、`arm_id` 区分配置；perf 的 SLO check 同样携带 Arm。Arm 的配置形状由各 harness
  强类型定义，共享的是语义和键，不是一个通用配置袋。
- **trace_id**：黑盒产物 ↔ 遥测的桥。各 harness 的 run 产物应尽量记录——eval `results.csv`
  已有列、perf `Outcome.meta` 已记、e2e 可放 `Outcome.metadata`；trace 的 `sibling_run`
  source 靠它把坏 case / 慢 Trial join 到链路归因。
- **`runs/<scope>/<run-id>/` + verdict.json**：波次产物的定位骨架（上节），消费方按它
  glob 全收。

perf 在一个 Trial 内还用 `window_id` 对齐时间切片；它是 perf 模型内的局部键，不提升为所有
harness 都必须实现的运行层级。

对齐键断一处，跨平面结论就拼不出来；修改这三组键的形状属于 spec 级变更，需过本文件。

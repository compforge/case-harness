# e2e_harness（api-mode）设计文档

> 范围：本文件讲 **e2e_harness 这一个 SDK**（确定性 API/SSE 契约测试）的内部设计。
> 仓库是三个 sibling SDK 的聚合（e2e / eval / perf），仓库定位与边界见 [`../AGENTS.md`](../AGENTS.md)；
> 非确定性的 agent/RAG 效果评测见 `eval_harness`、资源约束下的容量画像见 `perf_harness`（各有自己的 AGENTS.md）。
> 三者互不 import，一致性落在 `spec/` 数据格式（含统一判定出口 [`../spec/verdict-schema.yaml`](../spec/verdict-schema.yaml)）。

e2e_harness 是跨语言（Go + Python）的**确定性 API/SSE 契约测试** SDK（api-mode）：纯黑盒，
不 import 被测服务 internal，以 pytest 为执行底座。

## 1. 核心模型

一次契约测试就是一条 **trigger → collect → judge** 链：发一个请求、收集响应（含 SSE
事件流）、对响应做判定。判定分两类——硬断言（pass/fail）与软评分（连续指标）。

```
确定性 API 测试              混合（SSE / agent）
│ send JSON                 │ send chat / SSE
│ assert status=200         │ collect events
│ assert body.id != ""      │ assert + soft metrics
▼                           ▼
pass / fail                 pass/fail + score
```

| 步骤 | API 测试 | SSE / agent case |
|------|---------|------------------|
| trigger | sync HTTP POST | sync SSE |
| collect | JSON body | `Outcome.metadata.events` 里的 event list |
| judge | 硬断言 | assert + OutcomeMetric（latency 等） |

测试是**贴着 handler 代码的资产**：handler 上挂 `@case/@spec` 注解，discover 走 AST 扫描枚举，
scaffold 生成 pytest 脚本，meta block + case_hash 检测意图漂移。调度 / 重跑 / 报告都交给 pytest。

---

## 2. 执行链路

```
test_function
    └── BaseCase[State].execute()        # prepare / run / clean
        └── BaseRunner.trigger(Request)  # JSONRunner / SSERunner (sync)
            └── Outcome                  # status, body, headers, metadata.events, raw
                ├── AssertJudge          # 硬断言: 10+ assert methods
                └── OutcomeMetric        # 软评分: latency / status / event_count
```

适合场景：

- 注释式 case：handler 上挂 `@case("id", "desc", ...)` + `@spec(...)`
- discover + scaffold 工具一键 AI 生成 pytest 文件
- 单 case 单 pytest test，run/fail 走 pytest 原生流程

---

## 3. 分层架构

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4: Pipeline                                        │
│   pytest 直接调三段式 case；@case/@spec + discover/scaffold │
├─────────────────────────────────────────────────────────┤
│ Layer 3: Judge                                           │
│   AssertJudge (硬断言)                                    │
│   OutcomeMetric (Outcome 软评分: latency/status/...)      │
├─────────────────────────────────────────────────────────┤
│ Layer 2: Runner (sync + async siblings)                  │
│   JSONRunner / AsyncJSONRunner                           │
│   SSERunner / AsyncSSERunner                             │
│   shared: SSEParser / LineBuffer / events / headers      │
│   输入: Request    输出: Outcome                          │
├─────────────────────────────────────────────────────────┤
│ Layer 1: Core                                            │
│   Env / load_env (config.yaml + ${VAR} 插值)              │
│   Profile / Capability gating                            │
└─────────────────────────────────────────────────────────┘
```

**层间独立性**：

- sync 和 async runner 并立，调用方按场景选（pytest 用 sync）
- Outcome 是 runner ↔ judge 的统一中间表示
- judge 层不知道协议（不区分 sync/async runner 的产出）

---

## 4. Outcome：runner ↔ judge 的统一中间表示

```
        Sync side                    Async side
        ─────────                    ──────────
   BaseRunner.trigger()         AsyncBaseRunner.trigger()
            │                            │
            ▼                            ▼
        ┌──────────────────────────────────┐
        │        Outcome                    │
        │  status_code: int                 │
        │  body: dict | null                │
        │  headers: dict                    │
        │  duration_ms: int                 │
        │  metadata: dict (events here)     │
        │  raw: bytes                       │
        └──────────────────────────────────┘
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
       AssertJudge          events helpers
       OutcomeMetric        (find_event / collect_text / count_events)
```

关键点：

- Sync `JSONRunner.trigger` 和 async `AsyncJSONRunner.trigger` 产出**完全相同形状**的 Outcome
- SSE events 都在 `metadata['events']`，sync/async 路径用同一个 `runner.events` 模块抽取
- Outcome 可序列化 → 阶段可恢复（保存 outcome → 重跑 judge 不重跑 runner）

---

## 5. 生命周期：单 case 三段式

```
prepare → run → clean
```

| 阶段 | 职责 | 失败处理 |
|------|------|---------|
| prepare | 创建前置资源（可选） | 直接 fail（pytest fail） |
| run | trigger + assert / metric | 直接 fail |
| clean | best-effort 清理 | swallow 不 fail 测试 |

`BaseCase.execute()` 保证 clean 总会跑（`finally`），且 clean 抛错只 warning 不影响测试结论。

---

## 6. Judge：assert 与 metric

Judge 层有两类原语：

| 类型 | 适用 | 输入 | 输出 |
|------|------|------|------|
| `AssertJudge` 方法 | 硬断言 | Outcome | pass / 抛 AssertionError |
| `BaseMetric[Outcome]` 子类 | 软评分 | Outcome | MetricResult |

`BaseMetric` 是 generic 的单一抽象（`T` 为读入类型，本包恒为 `Outcome`）。内置
`LatencyMetric` / `StatusMetric` / `EventCountMetric`，配合 `score_outcome(outcome, metrics)`
在测试里横向打分。

统一面：

- `NAME` —— metric 标识；类属性，或 `__init__(name=...)` 实例覆盖（同一个类多实例用）
- `KIND` —— `"binary"`（0/1，报告渲染 `yes`/`no`）或 `"score"`（0~1 连续，渲染小数），默认 `"score"`
- `applies_to(target) -> bool` —— 过滤
- `score(target) -> MetricResult | Awaitable[MetricResult]` —— 抽象方法，sync/async 皆可
- `self.result(score, judgement)` —— 便捷 builder，把 NAME / KIND 自动填进 `MetricResult`

所有 metric 收敛到一个 `MetricResult(name, score, judgement, kind)`。

---

## 7. Runner 矩阵

| Runner | 协议 | sync/async | 输出 metadata 字段 |
|--------|------|-----------|-------------------|
| `JSONRunner` | HTTP JSON | sync | `{}` |
| `AsyncJSONRunner` | HTTP JSON | async | `{}` |
| `SSERunner` | HTTP SSE | sync | `{events: [...], event_count: N}` |
| `AsyncSSERunner` | HTTP SSE | async | `{events: [...], event_count: N}` |

所有 runner 产出统一的 `Outcome`。新增 runner 时：

- 新文件，inherit `BaseRunner` / `AsyncBaseRunner`
- 复用 `build_auth_headers` / `SSEParser` / `LineBuffer`（如适用）
- 把 protocol-specific 信息塞 `Outcome.metadata`，让 judge 层透明

---

## 8. Config

每个服务一份 `config.yaml`（语言无关 schema），见 [`spec/config-schema.yaml`](../spec/config-schema.yaml) 与 [`spec/conventions.md`](../spec/conventions.md)。要点：

```yaml
service:
  base_url: ${ENV_VAR:-default}

auth:
  tenant_id: ${TENANT_ID}
  user_id: ${USER_ID}
  headers:                    # 服务侧 header 名映射
    tenant_id: X-Top-Tenant-Id
    user_id: X-Top-User-Id

runtime:
  http_timeout_s: 120

profile: ${ENV_PROFILE:-full}

discover:                    # scaffold/discover 工具用
  source_root: ../server/api # 直接指向扫 @case/@spec 的目录
  test_root: tests           # 脚本按 case.group 落 <test_root>/<group>/（不镜像源码路径）

custom:                       # 服务自定义透传，框架不解析
  ttl_seconds: ${TTL:-60}
```

插值：

- `${VAR}` — 必须存在
- `${VAR:-default}` — 可选 default
- 仅在字符串值上做正则替换；nested 结构正常解析

---

## 9. 设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| sync + async runner 并立 | 是 | pytest 喜欢 sync；async 留给 async 密集的调用方 |
| Outcome 作为唯一中间表示 | 是 | 解耦 / 阶段可恢复 / sync↔async 接合 |
| `@case/@spec` 是 marker，零运行时副作用 | 是 | 不影响 handler 行为；discover 走 AST 不 import |
| `case_hash` 绑定 case 字段 + 所属 `@spec` | 是 | 改意图（desc/input/expect/forbid/spec）一处 hash 即标 stale；改 group 只挪文件不算 stale |
| MetricKind 类级 `KIND` 声明 | 是 | 一个 metric 不会同时既 binary 又 score；声明一次，scoring 注到每个 result 上 |
| 框架不 import 被测服务 internal | 是 | 黑盒原则，不随业务重构而破 |
| Go/Python 各自实现（共享 spec） | 是 | 语言生态差异大，强行共享不自然 |

---

## 10. 目录结构

```
e2e-harness/                     ← 聚合仓库
├── spec/                        # 语言无关约定
├── python/                      # Python 工程 (case-harness)：三个 sibling 包 + 共享 report_kit
│   ├── e2e_harness/            # 本文件主角（api-mode）
│   │   ├── core/               # Layer 1
│   │   ├── runner/             # Layer 2 (sync + async)
│   │   ├── judge/              # Layer 3
│   │   │   ├── assert_judge.py
│   │   │   └── metric/         #   BaseMetric[Outcome] + outcome / registry
│   │   └── api/                # api-mode: case / contract / discover / scaffold
│   ├── eval_harness/           # sibling 包：非确定性 agent/RAG 效果评测（见其 AGENTS.md）
│   ├── perf_harness/           # sibling 包：资源约束下的容量/资源画像（见其 AGENTS.md）
│   ├── report_kit/             # eval/perf 共用的中立报告 IR + HTML 渲染
│   ├── tests/                  # 三个 SDK 自身测试
│   └── pyproject.toml
├── go/                          # Go SDK (core / runner / judge / burst — 与 spec 一致；短期保持稳定)
├── docs/
│   └── design.md               # 本文件
└── examples/
    ├── api-test/               # JSON API 测试最小 demo
    ├── agent-test/             # SSE / agent case 最小 demo
    ├── go-service/             # Go API 测试样例
    └── python-service/         # Python API 测试样例
```

---

## 11. 服务接入

```bash
# pyproject.toml
[dependencies]
case-harness = ">=0.0.16"

# tests/conftest.py
from e2e_harness.conftest_helpers import env_fixture, runner_fixture, judge_fixture
env = env_fixture("config.yaml")
runner = runner_fixture()
judge = judge_fixture()

# tests/test_xxx.py — 手写 OR 用 scaffold 工具生成
pytest tests/ -v
```

详见 [`examples/api-test/`](../examples/api-test/) 和 [`examples/agent-test/`](../examples/agent-test/)。

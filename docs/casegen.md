# casegen：NL marker → 结构化 case 的 build-time 编译器

> 状态：**设计已定，未落代码**（决策见 §3.8）。可开工顺序：StubCompiler + orchestration + `check` 先行（确定性、可测），`DraftCompiler`（抄 eval-api 半自动）随后，自动 `LLMCompiler` 再后。
> casegen 是把 NL 代码 marker 前端接上已落地的"判定即数据" engine 的那一步
> （见 [`case-unification.md`](case-unification.md) §3.4 的"新增 compile"）。本文从设计合理性出发，定架构、留待决。
> 前置事实：engine / CLI / JSON+SSE 已落地（MR !97–!99），结构化 `judge.e2e.assert` 可执行；NL marker
> 抽取（`@case`/`@spec` → `discover()`）已存在。casegen = 把这两端用一次 build-time 编译接起来。

## 1. 理念

### 1.1 casegen 解决什么

现在 NL marker（人写意图、贴 handler）和结构化 engine（吃 `judge.e2e.assert`）之间断着一截。casegen 补上：

```
NL marker (@case/@spec)  ──discover(AST 抽 NL)──▶  Compiler(LLM, build-time)  ──▶  提交的结构化 case.yaml  ──▶  engine
   人写意图、co-located         已存在                  NL → {input, assert}            derived + committed + reviewed     已落地
```

### 1.2 三条承重区分

- **NL marker = INTENT 的源**（人写、co-located、可读）。**结构化 case.yaml = DERIVED 产物**（机器编、提交进 git、review 钉死）。
- **LLM 只在 build-time 出现**（编译时一次性），产物提交后 run-time 零 LLM——这是"判定即数据 + 确定性"成立的前提（见 case-unification §3.3）。
- **intent hash 链接两端**：marker 的 NL 变了才重编；没变就用已提交的产物。漂移检测靠它，不靠重跑 LLM。

一句话：**casegen 把"人写的 NL 意图"在 build-time 编译成"提交的结构化 case"，LLM 是一次性编译器、不是 run-time 依赖。**

## 2. 流程（三个 verb，对齐 Go casegen 的 list/sync/check）

```
casegen list   --source <dir>   列出 discover 到的 marker + 漂移态（in-sync / drifted / new / orphaned）
casegen compile --source <dir>  对 drifted/new 的 marker 调 Compiler(LLM) → 写 co-located case.yaml + intent hash；人 review 提交   [build-time, 用 LLM]
casegen check  --source <dir>   CI gate：比 intent hash，marker NL 漂了但 case.yaml 没重编 / 缺失 / 孤儿 → fail   [无 LLM，纯 hash]
```

- `compile` 是唯一调 LLM 的 verb，产物是 diff，人审后提交。
- `check` 是确定性闸门（无 LLM）：保证"提交的结构化 case 跟得上 marker 的意图"。
- run-time（`e2e run`）只吃已提交的 case.yaml，跟 casegen 完全解耦。

## 3. 关键设计

### 3.1 Compiler 是注入的抽象——SDK 不绑 LLM

casegen 核心只依赖一个 `Compiler` 协议；具体实现在 composition root（casegen CLI）注入：

```
Compiler(Protocol): compile(nl: DiscoveredCase, *, context) -> common.Case   # 抽象：NL → 结构化 case
  ├─ StubCompiler    确定性，测试用（验证 orchestration/drift，不调 LLM）
  ├─ DraftCompiler   v1：input 从 NL 投影，assert 留 draft（NL 意图内联）交 LLM/claude 填——见 §3.7
  └─ LLMCompiler     future：common.llm 自动填 assert（drop-in 替 DraftCompiler，无需改 orchestration）
```

为什么注入：① `e2e_harness/marker` 不能 import `eval_harness.llm`（三 SDK 互不 import）；② 注入让 orchestration（discover→compile→写 case.yaml→drift）能用 StubCompiler **确定性单测**，真正的填值（claude / 未来 LLM）只在边界接入。

**LLM client 上移 `common.llm`（已定）**：`eval_harness/llm/client.py:LLMClient` 是**跨 harness 中立基础设施**（eval 评分、e2e casegen 都要 LLM），上移 `common.llm` 后两边共用、不破 SDK 边界；`eval_harness.llm` 退化成 re-export。供未来 `LLMCompiler` 用——v1 的 `DraftCompiler` 还用不上它。

### 3.2 编译契约（Compiler 的职责）

| 输入（NL + 上下文） | → 输出（结构化 common.Case） |
|---|---|
| `@case` 的 NL `input` | `input`：请求 dict（method/path/body/…）|
| NL `expect` / `forbid` | `judge.e2e.assert: [{path, op, value}]`（op ∈ schema 8 个）|
| `@spec` 文本 + handler 签名/endpoint | 编译上下文（提示 LLM 字段名、错误码约定）|
| `id` / `facets` | 透传 |

- **结构化输出强约束**：LLM 用 JSON/tool 模式，输出 schema 限定到 8 个 op + response-view path 约定（`status`/`body.x`/`events[].x`/`event_count`）。
- **产物自校验**：编译完 `load_caseset + validate` + 断言 op∈枚举、path 可解析——LLM 吐不出 engine 会噎住的东西；不过校验即重试/报错。

### 3.3 确定性 + 漂移（build-time 的命脉）

- marker 有 **intent hash**（`discover` 已给：over NL content + `@spec`）。
- 编译产物 case.yaml 顶层记 `compiled_from: {<case_id>: <intent_hash>}`（casegen 自有元数据，`load_caseset` 忽略的顶层键；与 case 数据同文件、同 diff 可审）。
- `compile`：marker 的 intent hash ≠ 记录值（或无产物）→ 重编那条；相等 → 跳过（无 LLM、确定性）。
- `check`：从 marker 重算 intent hash 比记录值，漂移/缺失/孤儿 → fail。无 LLM。
- 结果：**NL = 意图源，case.yaml = 提交的编译产物，intent hash = 链接，check = 闸门**。LLM 的非确定输出被"提交 + review + hash 钉死"驯服。

### 3.4 co-location：产物贴 handler

编译产物落 `<module>_cases.yaml`（贴 handler 的 sidecar，**复用 `contract` 已有约定**），不入中央目录——保住 marker 的 co-location 价值（改 handler 就看见它的 case）。

### 3.5 复用 discover，退役 scaffold

casegen = **`discover`（复用：NL 抽取 + intent hash）+ `Compiler`（新）+ case.yaml writer（新）+ drift check（新）**，**替代** `scaffold` 的"生成 pytest body"。

- **留**：`contract`（`@case`/`@spec` + `CaseSpec`，NL 作者前端）、`discover`——迁入 `marker/`。
- **退役（步 3）**：`scaffold`（无 body 可生成）、`meta_block`（drift 改落 `compiled_from`，不在 test 文件）、`BaseCase/AgentCase/RPCCase` 测试类（engine + 协议适配器接走）。

### 3.6 跨语言

抽取 **per-language**（Python `discover` 用 python ast；Go casegen 用 go/ast）；**编译契约 + case.yaml 产物 + intent-hash drift 机制语言中立**。Go casegen 同形（go/ast 抽 → compile → case.yaml + check），可共享同一 schema 与（若上移 common 之外的服务化）同一 Compiler 服务；v1 各语言各自 casegen，共享 case.yaml 格式。

### 3.7 v1 走法 + 质量（参考 eval-api，先大体能用）

**v1 直接抄 eval-api 已验证的 loop**：eval-api 的 `engine.py` 就是 `discover → scaffold(骨架) → 把 status 甩给 claude 手填 → run`——LLM 是**人驱动的 claude 步骤，不是 in-code 自动调用**。casegen v1 同形，只把产物从 pytest body 换成**结构化 case.yaml**：

```
casegen compile → DraftCompiler 写 case.yaml 草稿（input 从 NL 投影，assert 留 NL 意图内联的 TODO）
                → 人/claude 填 assert（同 eval-api「甩给 claude」）→ 提交
casegen check   → load+validate + intent-hash 漂移闸门（无 LLM）
```

这样**不用先造自动化 LLM 客户端就能用**（"大体能用即可"），且复用 eval-api 趟过的工作流。`Compiler` 抽象让 `LLMCompiler`（common.llm 自动填）将来 drop-in。

- **质量闸门（按"trust + check"决策，不强制人 review）**：① 产物 `load_caseset + validate` 自校验（语法 / op∈枚举 / path 可解析）；② `check` 的 intent-hash 漂移闸门兜底；③（未来可选）round-trip：拿参考响应跑编译出的 assert，验证行为符合 NL 意图。
- prompt 要点（给 claude / 未来 LLMCompiler）：NL 意图 + `@spec` + op 词表 + response-view path 约定（`status`/`body.x`/`events[].x`/`event_count`）+ few-shot。
- 你伸手够 NL 表达"语义/模糊"判定时——那是 eval 面的活；casegen 编不出结构化 assert 的，正好暴露这个错配。
- **先在 已有服务的现成 NL case 上验证命中率**，再决定要不要、何时上自动 `LLMCompiler`。

### 3.8 决策（已定）

- ✅ Compiler 注入抽象（StubCompiler 测 orchestration）；**v1 = `DraftCompiler`**（骨架 + claude 填，抄 eval-api），future = `LLMCompiler`。
- ✅ 产物 = co-located `<module>_cases.yaml`；复用 `discover`，退役 `scaffold`/`meta_block`/BaseCase 测试类。
- ✅ 三 verb：list / compile / check（对齐 Go casegen）。
- ✅ **LLM client 上移 `common.llm`**（跨 harness 中立基础设施，供未来 `LLMCompiler`；v1 用不上）。
- ✅ **review：trust + `check` 的 intent-hash 闸门兜底**，不强制人 review 编译 diff。
- ✅ **`compiled_from` 用 case.yaml 顶层键**（同文件同 diff、`load_caseset` 忽略），不另起 `.lock`、不扩 schema。
- ✅ **质量：v1 抄 eval-api 半自动 loop、大体能用即可**；先在 eval-api 现有 NL case 上验命中率，再定是否/何时上自动 `LLMCompiler`。

仅剩实现时定的工程细节（不阻塞开工）：prompt 具体措辞、`DraftCompiler` 草稿里 assert-TODO 怎么内联 NL 意图。

## References

- 上游设计：[`case-unification.md`](case-unification.md)（判定即数据 / 多编写前端 / build-time 编译）
- canonical schema：[`../spec/case-schema.yaml`](../spec/case-schema.yaml)
- 现有抽取/标注/编译：`e2e_harness/casegen/{contract,discover,compiler}.py`、[`../go/AGENTS.md`](../go/AGENTS.md)
- 可复用 LLM client：`eval_harness/llm/client.py`（建议上移 `common.llm`）

# e2e_harness（确定性契约测试：判定即数据）

## 项目定位与边界

接口结果是确定的：合理输入 → 固定响应，错误输入 → 固定错误码。不关心"回答质量"——那是 `eval_harness` 的事；也不关心压力下的表现——那是 `perf_harness` 的事。

**命脉（判定即数据）**：case 是**结构化数据**——`input` + `judge.e2e.assert`（`{path,op,value}`）。`engine` 吃 case → 协议 runner 发请求 → 跑 assert → `verdict`（入口 `e2e run`，覆盖 JSON/SSE）。两个编写前端归一到同一 `common.Case`：手写 `case.yaml`，或 `@case/@spec` 的 NL marker 经 `casegen` 编译成 `case.yaml`（intent-hash 漂移检测）。**判定是数据，不是人写的测试体。** 详见 `docs/case-unification.md` / `docs/casegen.md`。

## 代码地图与核心模块

目录按 pipeline 阶段切，链路 `NL marker →(casegen) common.Case →(engine) verdict` 在结构上可读：

```
e2e_harness/
# ── ① NL authoring 前端：NL marker → common.Case（要推的写法，一个家）──
├── casegen/
│   ├── contract.py # @case/@spec marker + CaseSpec/Case + case_hash（marker 形状）
│   ├── discover.py # AST 扫 @case/@spec(+ *_cases.yaml) → DiscoveredCase（不 import 被扫源码）
│   └── compiler.py # Compiler seam(Stub/Draft/未来 LLMCompiler) + compile/check/list + casegen CLI
# ── ② 执行 + 判定即数据：common.Case → verdict ──
├── engine.py    # run_case/run_cases：common.Case → runner → assert 求值 → Verdict
├── assertion.py # judge.e2e.assert 求值器：{path,op,value} over response view（结构化、纯函数）
├── cli.py       # `e2e run case.yaml --base-url … → verdict.json`（+ __main__；JSON/SSE）
# ── ③ 复用层 ──
├── runner/      # 协议适配器（sync+async × JSON/SSE）→ 统一 Outcome（engine 复用）
├── judge/metric/# 软评分 BaseMetric[Outcome]
└── core/        # Env / load_env（${VAR} 插值）+ profile/capability gating
```

> 链路两端的 `common.Case`（入）/ `verdict`（出）/ `report` 在 `common/`——是 4 个 SDK 共享的
> harness-neutral seam，**不收进本包**（SDK 之间互不依赖）。
> 旧 api-mode（`scaffold` / `meta_block` / `case*`(BaseCase) / `judge.assert_judge` / `pytest_plugin` /
> `api.verdict`）已**整体退役**，原 `api/` 包随之删除、authoring 前端折叠进 `casegen/`——见 `docs/case-unification.md`。

## 关键约定

- **主链路**：`case.yaml → engine.run_cases → BaseRunner → Outcome → judge.e2e.assert 求值 → verdict.json`；入口 `e2e run`。判定（assert）是 case 里的数据，engine 通用执行，无 per-case 测试体。
- **case 两个编写前端**：手写 `case.yaml`，或 `@case/@spec` NL marker 经 `casegen compile` 编译（`casegen check` 是无-LLM intent-hash 漂移闸门；未填 assert 的草稿被 `e2e run` 当 skipped 观测、不 false-fail）。两者归一到 `common.Case`，engine 只认它。
- **Outcome 是 runner↔judge 契约**：`status_code / headers / body / duration_ms / metadata / raw`；SSE events 进 `metadata['events']`，engine 的 `response_view` 暴露 `events[]` / `event_count`。
- **Config**（`config.yaml`，语言无关 schema）：`service.base_url` / `auth.headers` / `runtime.*_timeout` / `discover.{source_root,test_root}`（discover/casegen 用）
- **verdict**（`spec/verdict-schema.yaml`）：`e2e run` 跑完落 `runs/<scope>/<run-id>/verdict.json`（scope 默认 `service.name`）。

## References

- 判定即数据架构（engine / 多编写前端 / 新老收敛）：[`../../docs/case-unification.md`](../../docs/case-unification.md)
- casegen（NL marker → 结构化 case 的 build-time 编译器）：[`../../docs/casegen.md`](../../docs/casegen.md)
- 跨语言约定（case/config schema）：[`../../spec/conventions.md`](../../spec/conventions.md)
- 统一判定出口：[`../../spec/verdict-schema.yaml`](../../spec/verdict-schema.yaml) + conventions.md「Run 产物与 verdict 出口」
- 接入示例：[`../../examples/api-test/`](../../examples/api-test/) / [`../../examples/agent-test/`](../../examples/agent-test/)

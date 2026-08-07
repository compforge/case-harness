# perf_harness 结果语义（result semantics）

> 状态：设计草案（批 2b，未实现）。本文定三件事：**SLO-as-config**（按预算判一次 run 成败）、**per-stage 聚合**（多 stage schedule 的诚实报告，= codex review P1#2）、**CO-correct 延迟**（开环按计划时刻计时 + 闭环标注）。
> 基线：批 2a 之后（`Outcome.dropped` / `RequestStats.n_dropped`+`drop_rate` / 报告饱和标记已落地）。设计取向参考了 k6 thresholds、Gatling assertions、Artillery ensure、wrk2/Gil Tene 的 coordinated omission。

---

## 1. 理念：三层 verdict + 延迟诚实

一次压测的"判定"分三个**高度**，各自输入不同、不该合并：

| 高度 | 输入 | 产出 | 现状 |
|------|------|------|------|
| **per-request** | 单个 `Outcome` | `Verdict(ok, error_kind)` | ✅ `Workload.judge`（批 !50） |
| **per-slice 聚合** | 一组 Outcome（trial / facet / **stage**） | `RequestStats` | ⚠️ 有 trial/facet，缺 **stage** |
| **per-run SLO 门** | run 内各 trial 的聚合指标 | run 级 pass/fail + 退出码 | ❌ 缺 |

> 三家工具共识：per-request 校验（Gatling check / k6 check / Artillery expect）与聚合 SLO 门（Gatling assertion / k6 threshold / Artillery ensure）是**两层**，输入与失败语义都不同。我们的 `judge` 已占第一层，本文补第二、三层。

**延迟诚实（CO）**：批 2a 已堵上最大的洞——`client_saturated` drop 不再当 0ms 延迟样本。本文收尾：开环按**计划发送时刻**计时（抗 dispatch 抖动的残余 CO），闭环百分位显式标注 **CO-biased**。

---

## 2. 流程

```
run
 └─ for each (resources × load) → Trial
      ├─ outcomes (sent + dropped)            # _drive_open / _drive_closed
      ├─ 聚合：overall + by_facet + by_stage   # RequestStats 切片（新增 by_stage）
      ├─ SLO 评估（对该 trial 的聚合指标）       # 新增
      └─ TrialResult(... slo: [SloCheck])
 └─ Run(passed = 所有 trial 完整运行且受门 SLO 通过) → CLI 退出码（0/1）
```

---

## 3. 关键设计

### 3.1 SLO-as-config（per-run 门）

SLO 是 Service Level Objective（服务级别目标），即我们希望系统达到的、可以量化验证的目标。

**配置**：Experiment 顶层新增 `slo:` 块，每条断言是 **metric × condition**——切片由 metric 的 **label** 决定（service / facet / stage 都是 label，无单独 scope）：

```yaml
slo:
  - { metric: p99_ms,     lt: 2000 }                            # 裸 = overall
  - { metric: error_rate, lt: 0.01 }
  - { metric: drop_rate,  lt: 0.01 }                            # 饱和预算（接 2a）
  - { metric: 'p99_ms{difficulty="complex"}',         lt: 5000 }   # facet 切片
  - { metric: 'request.throughput_rps{stage="hold@40"}', gte: 40 } # stage 切片
  - { metric: 'top.cpu_m{service="worker"}.peak',     lt: 1500 }   # 资源·某服务
  - { metric: 'prometheus.task_count{service="worker",task_type="batch",state="running"}.last', window: cooldown, lte: 0 }
```

- **metric**：`<name>{labels}.<stat>`（或 undotted 别名 `p99_ms`/`error_rate`/…，可带 label）。
- **condition**：`lt/lte/gt/gte/between`（`between: [lo, hi]`）。
- **window**：默认 `measurement`，读取负载测量窗口的既有汇总；`cooldown` 从
  `Workload.deactivate()` 返回后开始，在 `cooldown_s` 内对资源侧 gauge/counter 原始
  series 重新聚合。cooldown 需要 `cooldown_s > 0`，不支持请求分布或无原始 series
  的无原始 series 标量。
- **label**：`{service="…"}`（资源·某服务；`observe:` 开 `per_pod` 时该服务的 series 为 `{pod="…",service="…"}`，按 replica 拆）/ `{facetkey="val"}`（请求 facet 切片）/ `{stage="…"}`。统一 `<name>{labels}.<stat>` 寻址，和报告 by_facet/by_service pivot 同一个 group-by-label；资源 metric 是 trial 全局，不能配 facet/stage label。per_pod 服务没有 service 级聚合 series，`{service="…"}` 的 SLO 解析期直接报错（防 CI 门静默变 skip）。

**评估与产出**：每条断言对**每个 trial** 求值（trial 自带 overall/by_facet/by_stage 切片，resolver 按 label 路由）。数据结构：

```python
@dataclass(frozen=True)
class SloAssertion:                 # 来自 config
    metric: str                     # 含 label：duration_ms{difficulty="simple"}.p99
    op: Literal["lt","lte","gt","gte","between"]
    threshold: float | tuple[float, float]

@dataclass(frozen=True)
class SloCheck:                     # 求值结果（三态）
    assertion: SloAssertion
    observed: float | None          # None ⇔ state == "skipped"（slice 在该 trial 无数据）
    state: Literal["pass", "fail", "skipped"]
    # .passed = state=="pass"  /  .skipped = state=="skipped"  /  .failed = state=="fail"

# TrialResult 增加： slo: list[SloCheck]；slo_passed = 全部 state=="pass"（skip 也不算 pass）
# Run 增加：         passed: bool
```

读经 `MetricStore.query`：返回 `Missing` ⇒ `skipped`，否则比较得 `pass`/`fail`。**skip ≠ pass**（三态的要点）：

- `Run.passed`（CLI 退出码）先要求 trial 完整运行；对 SLO 默认**只看 fail**，measurement 的
  skip 仅在 `strict_slo: true` 时失败，cooldown 的 skip 始终失败，避免观测缺失被误读为已经回收。
- `slo_passed`（capacity 用）要求**全部 pass**——skip 的档不算确认容量（保守）。
- `TrialStop.early` 表示只得到部分测量窗口——即使已求值的 SLO 都通过，run 仍失败，且该档不计
  SLO-aware 容量；熔断保护被压服务，不能反过来成为容量达标证据。
- typo 进不了 skip：结构非法在解析期就 `ValueError`（见 metric-model.md §3.5）。

**🔶 开放问题 1：sweep 下哪些 trial 受门？** 容量扫描 `levels:[10,20,40]` 故意压到打挂，对全部 trial 施加同一 SLO 必然在高档失败。三个候选默认：
- (A) **全部受门**——简单但对"找拐点"型 sweep 不合理。
- (B) **scope 加 `level:<n>` 限定**——只门你真正承诺的档位，其余信息性展示。**（我倾向 B）**
- (C) 单档 run 才门、多档 sweep 只报告 SLO-aware 拐点（"满足 p99<2s 的最高档"）。

> 注：(C) 其实是个很有用的副产物——**SLO-aware 容量** = 所有 SLO 都过的最高 level。无论选哪个默认，报告都应输出这条。

**🔶 开放问题 2：fail-fast？** 借 k6 `abortOnFail`+`delayAbortEval`：某 trial 越线即停 sweep，并留一个 warmup 宽限避免早期抖动误判。建议作为 `slo` 块的可选开关 `abort_on_fail: true`，默认关。

### 3.2 per-stage 聚合（P1#2）

**问题**：多 level 的 `stages:`（spike/阶梯）现在把所有 post-warmup outcome 塞进**一个** `overall`、还按 `peak_level` 贴标签 → p99 把不同强度混成双峰，rps 是跨档平均，误导。

**方案**：给每个 Outcome 盖上**发射时所处 stage** 的标签，复用现成的 `by_facet` marginal pivot 出 `by_stage`。

- `Stage` 增加可选 `name`；未给则自动标 `hold@<level>` / `ramp→<level>`。
- `Schedule.stage_label(t) -> str`：复用 `intensity` 的 stage 遍历，返回 t 时刻活跃 stage 的标签。
- 引擎在 `_fire` / drop 处盖 `outcome` 的 stage 标签。
- 聚合时除 `overall`/`by_facet` 外再算 `by_stage`（同 `_request_stats` 切片）。

**ramp 段归属**（我之前 defer 的点，现在定）：ramp 段强度连续变化，**单独成桶**（`ramp→X`），不混进相邻 hold。容量结论只读 **hold 桶**（`hold@X`）；ramp 桶供观察过渡行为。

**标签 vs facet**：stage 作为**保留 facet key `stage`** 流过现有 pivot/csv，零新报告机制。为避免简单 run（单 ramp_hold，warmup 已吃掉 ramp）平白多一个单值 pivot，**仅当 schedule 有 >1 个 post-warmup hold 时才盖 stage facet**。

**诚实标注**：多 stage trial 的 `overall` 显式改称"post-warmup 平均（跨 stage）"，真正信号在 `by_stage`；报告对多 stage trial 注明"容量结论看 by_stage hold 桶"。

**🔶 开放问题 3**：`stage` 用保留 facet key（复用一切、但和 difficulty 等内容 facet 混在一张 by_facet 表）还是独立的 `by_stage` 维度（更清晰、需小改报告）？我倾向**独立 `by_stage`**（语义不同轴，报告单列一节），实现上和 by_facet 共用 `_request_stats`，只是渲染分开。

### 3.3 CO-correct 延迟

**开环 driver**：当前 `duration_ms` = 请求自身往返（actual_send→response）。由于 open driver **不等响应、每个到达直接起 task**（除 max_inflight），actual_send 已经≈计划时刻，残余 CO 只剩 **dispatch 抖动**（tick 粒度 + event-loop 迟滞）。方案：

- 在 `_drive_open` 记每个到达的**计划时刻** `intended_t`（accumulator 跨整数的时刻）。
- Outcome 同时带 **uncorrected**（service：response−actual_send，即现 `duration_ms`）和 **corrected**（response−intended_t）。
- 报告主用 corrected p99，副列 uncorrected；**两者差距 = 压力机自身 dispatch 落后**，是"测试是否可信/压力机是否成瓶颈"的直接诊断（呼应 2a 饱和标记）。

> 诚实说明：因为我们开环不阻塞派发,corrected−uncorrected 通常很小；这是 wrk2 在固定连接(closed-ish)场景的大头修正在我们这儿的**小修正**。真正的大洞(drop)已在 2a 堵上。

**闭环 driver**：N 用户 fire→pace→fire 是结构性 closed-loop，**无法无假设地修正**（没有外生计划时刻）。方案：
- 闭环 trial 的延迟百分位**显式标注 `CO-biased`**（报告打标），告诫勿当 SLO 尾延迟。
- 可选：若设了 `pacing`，用 pacing 间隔作为 assumed interval 做 HDR 式回填（`recordValueWithExpectedInterval`）给一个 corrected 数。**默认不做**，作为后续。

---

## 4. 数据结构改动汇总

| 模块 | 改动 |
|------|------|
| `model.py` | 新增 `SloAssertion` / `SloCheck`；`TrialResult.slo: list[SloCheck]`；`Run.passed: bool`；`Outcome` 加 `corrected_ms`（或塞 `meta`）；`RequestStats` 不变（SLO 直接读其字段） |
| `load.py` | `Stage.name: str \| None`；`Schedule.stage_label(t)` |
| `slo.py`（新） | SLO 解析 + 求值（纯函数：`(RequestStats 切片) → SloCheck`） |
| `engine.py` | `_fire`/drop 盖 stage 标签；`_drive_open` 记 `intended_t` + corrected 计时；`_aggregate` 增 `by_stage` + 跑 SLO |
| `report.py` | SLO 结果区（每 trial pass/fail + SLO-aware 容量）；`by_stage` 区；corrected/uncorrected 双延迟列；闭环 CO-biased 标 |
| `config.py` | 解析 `slo:` 块 + 校验 metric(含 label)/op |
| `cli.py` | run 末按 `Run.passed` 设退出码 |

**不变**：`Workload`/`Probe`/`Provisioner`、per-request `judge`/`Verdict`、`by_facet` 机制（`by_stage` 复用它）。

---

## 5. 实施次序（建议拆 MR）

1. ✅ **per-stage 聚合**（3.2）——已实现（`Stage.name`/`Schedule.stage_label`/`is_multi_stage`/`stage_durations`、`Outcome.stage`、`TrialResult.by_stage`、报告 §2b + by_facet.csv 的 `stage` 行）。
2. ✅ **SLO-as-config**（3.1）——已实现（`slo.py` 纯求值、`SloAssertion`/`SloCheck`、`Experiment.slo`/`abort_on_fail`、`Run.passed` + CLI 退出码、报告 SLO 区 + SLO-aware 容量）。决策落地：受门策略选 **B**（assertion 加 `level:` 限定档位）；`abort_on_fail` 默认关；闭环 CO-biased 标注一并并入（报告 §1 注脚）。
3. **CO-correct 延迟**（3.3）——开环 corrected 双报，最后做（收益最小、最独立；闭环 CO-biased 标注已随步骤 2 落地）。

每步独立加测试（`test_perf_*`），独立可验证。

---

## 6. 开放问题（已拍板）

1. ✅ **SLO sweep 受门策略** → **B**：assertion 加 `level:` 限定档位；并始终输出 SLO-aware 容量。
2. ✅ **fail-fast** → 支持 `abort_on_fail`，**默认关**。
3. ✅ **stage 维度** → **独立 `by_stage`**（步骤 1 已落地）。
4. ⏳ **闭环 HDR 回填** → **挂后续**；步骤 2 先只标 CO-biased。

---

## References
- 加压模型：[`load-model-redesign.md`](load-model-redesign.md)
- per-request verdict：`workload.py` `judge`/`Verdict`
- 聚合与报告：`engine.py` `_request_stats`/`_aggregate`、`report.py`
- 2a 饱和/drop：`model.py` `Outcome.dropped`/`RequestStats.drop_rate`

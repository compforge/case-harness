# perf_harness（资源约束下的容量与资源画像）

## 项目定位与边界

不测对错（`e2e_harness`）、不测质量（`eval_harness`），测**容量与资源画像**：把服务放到某个资源档下、施加压力、观察它随时间的表现，回答"在 xx 资源 + xx qps 下扛得住多少、cpu/内存/错误率如何"。**自给自足**，不 import 另两个 SDK；k8s 只活在 `subject.py`（HelmProvisioner）+ `observe/k8s.py` 两处。

### 脊柱

```
一个 Experiment = ResourceProfile(资源档) × LoadProfile(负载档) 的网格
每个格子(Trial)由 Workload 发带 facet 的 Case、Probe 周期采样 → 一张 metric 表
report / SLO / analyze 都是对这张表的查询（<family>{labels}.<stat>）
```

## 代码地图与核心模块

顶层目录顺序即数据流（subject → drive → observe → metric → 消费者）：

```
perf_harness/
├── cli.py · config.py · sh.py   # 入口与装配；config 解析 + fail-fast 校验
├── model.py        # 名词层（纯数据）：Outcome/Verdict/Trial/Run/TrialStop/ResourceProfile
├── subject.py      # 压谁：Subject(name+target+provisioner?) + HelmProvisioner（唯一碰 helm 处）
├── engine.py       # 纯编排：扫网格，每格 apply → drive → observe → reduce
├── drive/          # 怎么压（扩展点①）
│   ├── load.py     #   LoadProfile：model(open/closed) × Schedule(强度随时间) × Pacing
│   ├── workload.py #   协议适配 fire/judge + register_workload；MockWorkload
│   └── scheduler.py#   驱动循环：开/闭环 + 熔断 DECIDE + drain/cancel ENACT → TrialStop
├── observe/        # 看什么（扩展点②）；FamilySpec 单表声明 metric 元数据
│   ├── base.py     #   Probe ABC + client/scrape 探针 + observe_loop（采样循环）
│   └── k8s.py      #   top/rss/restart/limits（kubectl 系探针，纯函数解析器可单测）
├── metric/         # 收腰：唯一的那张表
│   ├── family.py   #   纯模型：MetricFamily(side/value_kind)+summary union+Missing+寻址
│   ├── store.py    #   MetricStore：消费方唯一读面（query/pivot/rows）
│   └── reduce.py   #   铸币点：outcomes/series → typed summary + caveats
├── slo.py · verdict.py   # run 级门（三态）；跨 harness verdict.json 出口
├── runio.py        # raw/model 两层落盘 + load_run（离线重建）
├── report/         # 视图层：render（md/html/csv）+ palette（配色=显示策略，不进模型）
└── analysis/       # 四个确定性透镜（capacity/resource/latency/validity）→ Observation
```

## 关键约定

### 脊柱（动它先想清楚）

- **metric 是收腰**：组件产 metric、分析/报告读 metric，只经 `MetricStore` 按 `<family>{labels}.<stat>` 寻址，两边互不知道对方；service / facet / stage 都是 series 的 label。模型细节见 `docs/metric-model.md`。
- **`side` 一位定切片合法性**：request 侧可切 facet/stage，resource 侧只可切 service（/pod）——是 family 上的数据，不是按名字特判的规则；SLO 解析期双向校验。
- **加压是 x 轴不是 metric**：响应面 `metric = f(资源档, 负载档, slice)`；资源档 × 负载档是 trial 坐标。

### 扩展点（业务接入只碰这两个）

- **`Workload`**（怎么压 + 怎么判）：`fire(case)` 只记原始观测，`judge(outcome)→Verdict` 才裁决（纯函数，可离线重判）；SSE"200 但流坏了"靠 override `judge`。各服务在自己项目写、`register_workload` 注册，框架只内置 mock。
- **`Probe`**（看什么）：`families` 单表声明元数据（FamilySpec：unit/value_kind/description，describe/summarize/Engine 共读），`sample()` 周期采样；Source 不绑 k8s（client/http/k8s 句柄），一次 run 混挂多 Source 才能做瓶颈归因。

### 判定与可信度语义（细节见 docs/result-semantics.md + metric-model.md §3.6-3.8）

- 三层 verdict：per-request `judge` → per-slice `RequestStats` → per-run SLO（三态，skip ≠ pass、不计 capacity；typo 在解析期就死，进不了 skip）。
- 两类停止不合并：within-trial 错误率熔断（实时保护被压服务）vs between-trial `abort_on_fail` SLO 门；每个 trial 以结构化 `TrialStop` 收尾。
- 只有完成的请求才是延迟事实：drop（未发出）与 cancel（在途被切）绝不进延迟直方图——防 coordinated omission；caveat（co_biased/high_drop/…）随值走。
- 观测面 ⟂ 判定面：scrape/derived 默认只观测；影响成败的唯一通道是显式 SLO 引用。

### 产物与运行

- 一次 run = 一个命名 experiment，产物落 `runs/<experiment>/<run_id>/` 累积不覆盖；落盘三层 raw（outcomes.jsonl/timeseries.csv）→ 模型（run.json，schema 版本化，`load_run` 离线重建）→ 视图（report/CSV，纯下游）。
- `verdict.json` 是跨 harness 契约（spec/verdict-schema.yaml，devloop 消费），改动需四家对齐。
- 请求侧指标走客户端 Outcome（没 `/metrics` 的服务也能压）；`/metrics` 只喂资源侧。

## References

- 使用指南（user 视角）：[`README.md`](README.md)
- metric 模型（含 otel-collector 对照）：[`docs/metric-model.md`](docs/metric-model.md)
- 结果/SLO 语义：[`docs/result-semantics.md`](docs/result-semantics.md)
- 加压模型细节：[`docs/load-model-redesign.md`](docs/load-model-redesign.md)

# perf_harness

把一个服务放到某个资源档下、施加压力、观察它随时间的表现，回答 **"在 xx 资源 + xx 压力下，
扛得住多少、表现如何"**。不测对错（`e2e_harness`）、不测回答质量（`eval_harness`）。

模型三行：

> 一个 **Experiment** = 资源档（ResourceProfile）× 负载档（LoadProfile）的网格；
> 每个格子（**Trial**）由 Workload 发带 facet 的 Case、Probe 周期采样，产出一张 **metric 表**；
> report / SLO / analyze 都是对这张表的查询（统一寻址 `<family>{labels}.<stat>`）。

## 最短路径

```yaml
# my-exp.yaml —— 压一个已部署的服务，最小配置
name: chat-sizing
subject:
  name: chat-server
  base_url: http://chat-server.vke-system.svc:8001
  k8s: { kubeconfig: ~/.kube/a-dev, namespace: vke-system,    # 可选：开 k8s 资源观测
         app_label: app.kubernetes.io/name=chat-server }

workload: { name: chat, path: /api/v1/chats/, timeout: 180 }  # 你注册的协议适配（见下）

cases:                                  # 混合流量：weight = 本实验怎么用这个 case
  - { id: hello,  weight: 70, facets: {difficulty: simple},  input_file: ./q_hello.json }
  - { id: caocao, weight: 30, facets: {difficulty: complex}, input_file: ./q_caocao.json }
facets: { difficulty: { values: [simple, complex], ordered: true } }

load: { model: closed, levels: [5, 10, 20, 40], ramp_s: 20, steady_s: 120 }  # 容量扫描

observe:                                # 看谁（资源侧）；省 k8s 的条目 = subject 自己
  - { name: chat, probes: [metrics, top, rss, limits] }

slo:                                    # 可选：run 级门 → CI 退出码
  - { metric: error_rate, lt: 0.01 }
  - { metric: 'p99_ms{difficulty="complex"}', lt: 30000 }
```

```bash
# 离线 smoke（无需服务/集群，内置 MockWorkload）：
cd python && uv run python -m perf_harness.cli run perf_harness/examples/mock.yaml
# 真实压测（在你自己的项目里，那里 register_workload 了你的适配）：
python -m perf_harness.cli run my-exp.yaml          # 非 pass 即非零退出（CI gate）
python -m perf_harness.cli analyze <run_dir>        # 确定性分析透镜（容量/资源/延迟/有效性）
python -m perf_harness.cli report  <run_dir>        # 从模型层重渲染报告（不重压）
```

产物落 `runs/<experiment>/<run_id>/`，累积不覆盖。三层分离——改报告版式不碰前两层：

```
outcomes.jsonl · timeseries.csv    # raw：每请求事实 / probe 采样
run.json                           # 模型层（schema 版本化）：分析的唯一入口，load_run 可离线重建
report.md/html · summary.csv · by_facet.csv · verdict.json   # 视图层（人看的，纯下游）
```

## 配置面速查

| 顶层 key | 干什么 | 细节 |
|---------|--------|------|
| `subject` | 压谁：`base_url`/`headers`/`k8s`；可选 `provisioner: {type: helm, …}` 让 harness 自己扫资源档 | 不写 provisioner = 直连已部署服务 |
| `resources` | 资源档列表（workers/cpu/memory/replicas），网格第一轴 | 无 provisioner 时仅作标注 |
| `load` | 压多狠、怎么随时间变：`model`(open/closed) + `levels` 或 `stages` + pacing/熔断/优雅停 | [`docs/load-model-redesign.md`](docs/load-model-redesign.md) |
| `workload` | 协议适配器（你写、`register_workload` 注册；框架只内置 mock） | 见下「接入一个服务」 |
| `cases` / `facets` | 混合流量（输入 + facets + weight）；报告按 facet 边际拆 | 聚合 p99 双峰没意义，拆开才有用 |
| `observe` | 资源观测：看谁（self+下游同一形状）、抓什么（metrics/top/rss/restart/limits + `scrape:` 任意 Prometheus 族） | `service` 是 label，报告按服务分小节 |
| `derived` | 两个 counter 族的比值（Δnum÷Δden，如服务端 ttft 均值），reduce 期按 label 自动 join | 观测性的；要当门需显式 SLO 引用 |
| `slo` | run 级断言（三态 pass/fail/skipped，skip ≠ pass）→ 退出码与 SLO-aware 容量 | [`docs/result-semantics.md`](docs/result-semantics.md) |

## 接入一个服务

1. 在**你自己的项目**里写 `Workload` 子类：`fire(case)` 发一个请求、回**原始** Outcome
   （不下结论）；协议特有的成败规则 override `judge(outcome)`（如 SSE "200 但流坏了"）。
   `stream_sse` 帮你发 SSE 并自动记 `ttft_ms`。
2. `perf_harness.register_workload("<name>", lambda cfg: YourWorkload(**cfg))`。
3. 复制 [`examples/chat.yaml`](examples/chat.yaml) 改 `workload.name` / `subject` / `load`。

## 进阶指针

结果可信度语义全部收敛在文档里，README 不展开——按需查：

- **加压模型**（open/closed、ramp≠warmup、max_inflight 防 CO、熔断与优雅停）→
  [`docs/load-model-redesign.md`](docs/load-model-redesign.md)
- **结果与 SLO 语义**（三层 verdict、三态 SLO、TrialStop、capacity 口径）→
  [`docs/result-semantics.md`](docs/result-semantics.md)
- **metric 模型与寻址**（family/series/label、side、caveats、Missing、SLO 引用合法性）→
  [`docs/metric-model.md`](docs/metric-model.md)
- **框架开发者视角**（代码地图、扩展点、约定）→ [`AGENTS.md`](AGENTS.md)

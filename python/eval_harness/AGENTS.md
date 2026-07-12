# eval_harness（table-centric：非确定性评测）

## 项目定位与边界

接口产出是非确定的（自然语言回答 / 工具调用序列），关心回答质量、是否拒答、引用是否准确。**实验优先**：一次评测是一个 Experiment，可在多个对照臂（Env）上跑同一评测集，做跨模型/跨参数对比。

### 脊柱

```
evalset ──( solver 补 answer / scorer 补 metric )──▶ Worksheet（大表）──pivot──▶ report
```

一个 evalset，过一个或多个 Env，产出一张内存 Worksheet，reconciler 逐 cell 填，report 纯 pivot 渲染。**不是 prepare→run→eval 的串行流水线**。

## 代码地图与核心模块

```
eval_harness/
├── model/       # experiment(Experiment/Env/Business/LLMSpec) · evalset(EvalSet/eval_view/FacetSchema；case=common.Case) · sample(MetricResult)
├── worksheet/   # worksheet(Worksheet/Row/cells) · checkpoint(jsonl + 异步 Checkpointer)
├── metric/      # base(BaseMetric+WEIGHT) · aggregate · builtins · registry
├── schedule/    # ratelimit(per-endpoint AIMD) · reconcile(ReconcileEngine)
├── report/      # pivot(env/facet/compare) · render(md/csv)
├── produce/     # mock(echo)；真实 producer 落在消费方仓库
└── config.py · engine.py(run_experiment) · cli.py · materials/
```

## 关键约定

- **Experiment** = `business`(基线 SUT 配置) + `envs` + `evalset` + `metrics` + `weights`；单次运行 = 1-Env 实验
- **Env**（对照臂）= `business ⊕ overrides`，分 **heavy**（provisioned resource+sources，有 prepare/clean 和复用 key）+ **light**（model/params，按调用施加）；`Env.key` 只 hash heavy 字段 → 只换模型的臂共享同一份 provision
- **Worksheet**（大表）= rows = (env × case)，每 cell 带 PENDING/OK/FAILED；引擎唯一真相 + checkpoint
- **reconciler**（缺啥补啥）= 扫描非 OK 且依赖就绪（provision→solve→score）的 cell 派工填；per-endpoint rate-gate；resume = reload 后再扫一遍
- **MetricResult 双通道**：quality（0~1 → 加权 overall）vs measurement（value+unit，p50/p95，不进 overall）；`score=None` = 弃权（不当 0）
- **产物两形态**：`worksheet.jsonl`（无损 checkpoint，可断点续跑）vs `results.csv`（有损扁平投影，人工 review 用）
- 真实 Provisioner/Solver 是消费方关切，落在消费方仓库；本包用 `--mock` 自跑

## References

- 使用指南（user 视角）：[`README.md`](README.md)

# trajectory_harness

## 项目定位与边界

trajectory_harness 评估 agent 的**决策与行动序列**：是否反复调用同一工具、绕路、遗漏必要
步骤，或在某一步做了错误决定。它不替代 eval_harness 的最终回答质量评分，也不替代
trace_harness 对物理 span、耗时与错误传播的归因。

外部 session / trace 先经 `TrajectoryLoader` 投影为稳定的 `Trajectory`，Evaluator 只消费
该中间格式，不感知 OTel、框架 session 或存储后端。

## 代码地图与核心模块

```
trajectory_harness/
├── model.py             # Trajectory / Step；message 直接沿用 OTel GenAI role+parts 形状
├── loaders/             # 外部记录 → Trajectory；base 契约 + OTel JSON 默认实现
├── evaluate.py          # Evaluator 契约、Evaluation 与 evaluate 编排函数
├── evaluators/          # 确定性与模型 evaluator；一个文件一种判定
└── tests/               # 中间格式、loader 与 evaluator 契约测试
```

## 关键约定

- **OTel 是外部词汇，不是内部依赖**：operation 与 message parts 对齐 OTel GenAI 语义约定，
  但核心模型不依赖某个 OTel SDK 或仍在演进的生成类型。
- **只有 Loader 知道来源格式**：session/OTLP/框架私有字段止于 Loader；Evaluator 只读
  `Trajectory`。
- **Evaluator 统一输出证据**：score 归一到 0~1，无法适用时返回 `None`；label/explanation
  供人读，`step_ids` 让结论能回到原轨迹核验。
- 不新增 Operator / Engine 层：确定性规则、reference match 与 LLM judge 都实现同一个
  Evaluator；编排先保持为纯函数，出现真实生命周期后再升级。

## References

- 设计与外部实现取舍：[`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md)
- OTel GenAI 语义约定：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>

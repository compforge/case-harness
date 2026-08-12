# Perf conformance

这里的 fixture 是 Perf Harness 跨语言契约的可执行样例，不属于 Python 或 TypeScript 任一实现。
每种语言实现至少要证明自己能读取公共 fixture，并保持以下语义：

- `trial` / `arm.id` 是同一次 Trial 的稳定对齐键；
- Outcome 的 `t` 是 dispatch 相对 Trial 起点的秒数；
- `metrics` 保存每请求指标，`meta` 保存 `trace_id` 等遥测关联键；
- 未知可选字段不会导致 reader 失败。

fixture 的字段定义见 [`../../spec/perf-contract.md`](../../spec/perf-contract.md)、
[`../../spec/perf-run-schema.yaml`](../../spec/perf-run-schema.yaml) 和
[`../../spec/perf-outcome-schema.yaml`](../../spec/perf-outcome-schema.yaml)。

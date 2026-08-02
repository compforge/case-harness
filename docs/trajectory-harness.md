# trajectory_harness 设计

## 1. 理念与概念

trajectory_harness 回答的是：**agent 为得到结果而采取的决策与行动序列是否合理**。同一次
执行可被三个视角消费，但问题不同：

| 视角 | 主要问题 | 分析本体 |
|------|----------|----------|
| eval_harness | 最终回答好不好 | response / sample |
| trajectory_harness | 过程中的选择好不好 | 有序 Step |
| trace_harness | 物理链路哪层先反常 | span 投影出的 Node |

首版只增加四个核心概念：

- **Trajectory**：一次 agent/workflow 执行的有序步骤集合。
- **Step**：一次模型、工具、agent、plan、retrieval 等操作；保留 id、parent、顺序、耗时与
  输入/输出 message。
- **TrajectoryLoader**：把一种外部记录格式投影成 Trajectory。
- **Evaluator**：对一条 Trajectory 给出 score、label、explanation 与证据 step_ids。

不再另设 Operator 或 Engine：确定性算子、reference match、LLM judge 都是 Evaluator；多个
Evaluator 的编排目前只是 `evaluate(...)` 纯函数。

### 外部规范与实现取舍

业界尚没有一份可直接采用的“完整 Trajectory 标准”，现有项目覆盖的是不同切面：

1. **OTel GenAI semantic conventions** 提供最适合作为外部边界的 operation 名称、span
   关系以及 `role + parts` message schema，也定义了 evaluation 的 name / score / label /
   explanation；但它不定义评估引擎或统一 Trajectory 对象。
2. **langchain-ai/agentevals** 把 trajectory 视为 OpenAI/LangChain message 序列，提供
   strict/unordered/subset/superset 与 LLM judge。它适合做 Evaluator 参考或可选适配，但其
   核心类型绑定 LangChain/OpenAI message，且 deterministic match 主要比较 tool calls，不能
   作为本项目的中间格式。
3. **agentevals-dev/agentevals** 已覆盖 OTLP/Jaeger 的大量兼容细节，值得参考 Loader 的边界
   case；但其 evaluator 协议把一次 invocation 压成 user/final response + 分离的 tool
   calls/responses，丢失完整顺序和父子关系，同时核心依赖 Google ADK 与服务端组件，不适合
   作为轻量 SDK 依赖。

因此本项目拥有一个很薄的 IR：Step 的 message 原样采用 OTel 形状，执行关系只补 OTel
message 没表达的 id/parent/time/status。这样不是另造协议，而是把外部标准拼成 Evaluator 真正
需要的最小稳定面。

## 2. 流程

```
OTLP / session JSONL / framework trace
              │
       TrajectoryLoader       # 来源私有字段止于此
              ▼
     Trajectory + ordered Step
              │
   ┌──────────┼──────────────┐
   ▼          ▼              ▼
deterministic reference    LLM judge
 evaluator      match       evaluator
   └──────────┬──────────────┘
              ▼
 Evaluation(name, score, label, explanation, step_ids)
              ▼
 applicable score 加权汇总；None=abstain，不按 0 计
```

当前 OTel Loader 接受标准 OTLP JSON、Tempo OTLP wrapper 与 flat JSONL；从
`gen_ai.input.messages` / `gen_ai.output.messages` 读取标准 message。工具 span 只有
`gen_ai.tool.call.*` 时，Loader 会投影为同形的 tool_call / tool_call_response parts，让下游
Evaluator 不必维护两套输入。

## 3. 关键设计

### 3.1 轨迹不是 trace tree 的别名

trace_harness 保留物理遥测事实并分析耗时、错误传播和拓扑；trajectory_harness 只保留 agent
决策所需的语义步骤。两者可以消费同一份 OTel 数据，但不互相 import：一个回答“哪里坏”，
另一个回答“这条行动路线好不好”。共享能力等出现第二个稳定实现后再下沉 `harness_common`，
不为了复用先制造大一统模型。

### 3.2 score 与执行健康分开

Evaluator 的 score 统一为 0~1；不适用或证据不足返回 `None`，汇总时剔除。轨迹缺失、Loader
失败、Evaluator 异常属于执行健康，不能伪装成 0 分或 clean。label 是低基数机器维度，
explanation 给人读，step_ids 是可核验的证据锚点。

### 3.3 首个规则只验证最小闭环

`RepeatedToolCallEvaluator` 检测相同 tool name + arguments 的再次调用。存在 execute_tool
步骤时以真实执行为准；只有模型 message 时才退化到 tool_call parts，避免同一次调用在模型
输出和工具 span 中被重复计算。后续 CCR 的 file_read 覆盖率、搜索轮次、Unit 未完成等规则，
应作为独立 Evaluator 增量加入，而不是扩张核心模型。

# trace_harness

## 项目定位与边界

e2e-harness 的第四个 SDK：trace/span 分析框架。前三个 harness 把系统当黑盒（发请求看
响应），trace_harness 开盒——消费遥测（OTel/Jaeger span），回答"链路内部哪一层先反常"。

**长期目标**：把一套**概念**（类型化 node 树 / 派生 facts / 判读 finding / 渲染 facet）与**流程**
（ingest→feature→diagnose→render）咬合成一个可生长的系统，靠**持续新增规则**（detector，case as
code）辅助分析、排查 trace 里的问题——排查中每定位一类新坏模式就沉成一条，框架越用越懂、越会自己说话。

设计理念、流程、决策记录见 [`../../docs/trace-harness.md`](../../docs/trace-harness.md)，本文件只给代码地图与改动入口。

与姐妹 harness 互不 import；`common`/`report_kit` 是唯一共享。域专属 kind（AS 的
aigw/sandbox）不进本包，随域包留在消费方（如 trace-as skill），用 `spec.merge` 叠加。

## 代码地图与核心模块

目录即数据流主链：**ingest 把 raw 变成 model；kinds 是唯一领域代码；analyze/view/corpus
都从 model 扇出**。assemble 是整条链唯一的领域边界，nodes.json(model/ir) 是 assemble(域感知)
与 view/explore(通用) 之间的契约。

```
trace_harness/
├── model/            # 分析枢纽（零域知识）：所有消费者围绕它扇出
│   ├── span.py       #   NormSpan：归一物理 span，刻意不带语义 kind 字段
│   ├── node.py       #   Node 分析本体(不内嵌 children，只带 parent 边；brief/error_text assemble 烤)/Field/Finding
│   ├── spec.py       #   KindSpec(matches/claims/build + metrics/rules/obs_hole + project) + SpecSet + merge
│   ├── context.py    #   TraceContext：单 trace 建模单元(内存事实源)，dispatch 挂这；view() 惰性建树
│   ├── viewtree.py   #   视图期惰性索引(仅渲染/火焰/最近祖先用，分析侧从不持树)
│   └── ir.py         #   TraceView + nodes.json dump/load：模型的可序列化形态(渲染面契约·域无关)
├── kinds/            # 唯一领域代码(通用 genai；域专属 AS kinds 留消费方，spec.merge 叠加)
│   ├── base.py       #   generic 残余 spec + duration 基线度量
│   └── genai.py      #   OTel GenAI 通用 spec：model-call / tool-call / agent / http(LLM 端点 http 自成 node，1:1 不再吸附)
├── ingest/           # raw → model（主链入口 + 唯一领域边界）
│   ├── sources/      #   采集协议(唯一知道后端的层)：base(Source/SpanQuery/Fidelity) / jaeger_file / opensearch
│   ├── load.py       #   build_context_from_spans(Source 无关) / build_context(文件)
│   └── assemble.py   #   fusion 七步 + bake_features + bake brief：raw span → list[Node]+父子边，末尾拉 eager Feature 烤 facts
├── feature/          # 从 node 算命名值：统一 build/derive/repro（Feature 在 bake×读raw 平面上的点），与 view/analyze 对称
│   ├── feature.py    #   Feature(produces/applies/compute/bake)：bake=True 烤进 facts、False 按需(curl/bash)
│   ├── ctx.py        #   Ctx：pull+memo，get(node,name) 递归拉依赖+缓存 → 无 order/无 bottom-up；raw 随数据源
│   ├── registry.py   #   register_feature / producing(name,node)：generic 在 harness、biz(agent_type/curl)在 skill
│   ├── engine.py     #   bake_features(eager 烤进 facts，取代 run_derive) / lazy_features(consumer 按需取)
│   └── builtins.py   #   harness 自带 Feature：self_ms(=dur−子并集) / http_status(model-call 从 http 子卷)
├── analyze/          # model → findings/gates（__init__：node-scope+table-scope 统一注册表）
│   ├── diagnose/     #   node-scope 判读：__init__ 汇流 / registry(register_detector 全局注册表) / detectors(内置拓扑) / outliers / series(trend) / patterns / probes
│   └── verdict.py    #   gates → verdict.json 投影(统一判定出口，照 perf 模式)
├── view/             # model(+findings) → 各种呈现（perspective 层：node tree 只管结构，重点在这定）
│   ├── facet.py      #   Facet(match/priority/brief/layout/render)+ChildOp(Expand/Fold/Aggregate/Group/Hide/Summarize)：按 node 分派的渲染策略；Aggregate/Group 是 biz 折叠手柄(Group 异类·可 collapsed/展开)
│   ├── registry.py   #   FacetRegistry/register_facet：priority 择一(DefaultFacet 兜底)，skill 注册 biz facet
│   ├── engine.py     #   render(view,findings)→DisplayNode + 序列化 to_md_lines/render_md/render_callstack：dispatch facet·执行 ChildOp·finding 按 node_id 绑(折叠上浮)；signal-aware collapse(信号免疫·≥error 浮出) + 同构 Group 合并 ×N
│   ├── display.py    #   DisplayNode：脱 ctx/kind 的显示树(md/html/treecli 共用)
│   ├── facets/       #   harness 通用 facet(零 biz)：ServiceFacet / ModelCallFacet(默认 Hide http 子)（biz facet 随域包注册）
│   ├── callstack.py  #   findings_block + render_callstack(legacy 无 facet 原样树)；md/show/html 已切 engine·facet
│   ├── explore.py    #   render_explore：treecli 渲染核(缩略图 + expand + 同构兄弟折叠)
│   ├── state.py      #   ViewState(展开集/focus) + selector + iso_sig：treecli 的状态与寻址
│   ├── text.py       #   调用栈框线 tree(├─└─，读 Finding 上色)
│   ├── interactive.py #   bespoke 交互 HTML(折叠展开·火焰图·span 下钻)，走 engine·DisplayNode·facet 折叠；唯一 HTML(静态用 md，旧 html.py 已删)
│   └── series.py     #   (kind,metric) 跨迭代 sparkline 文本
├── corpus/           # many-model → 三表 + 算子：error_signature/fleet_outlier/contrast/diff/pattern_rates；
│   │                 #   store(parquet→jsonl) / report / experiment(yaml runner)
│   └── cohort.py     #   Cohort：跨 trace 分析单元；single=of(trace_id)、cross=select(query)，N=1 即 single
└── cli.py            # single<jaeger> | batch<exp.yaml> | cohort<jaeger> | treecli<nodes.json|jaeger> [verb handle]
```

**主链（source → 诊断/渲染）**：

```
source ─ingest───→ NormSpan 集
       ─assemble─→ node 树（matches/claims 定结构 + 父子边）
       ─feature──→ node 树（+ eager Feature 烤 facts，结构不变）  ← 至此 node 树 / nodes.json 完整
       ─diagnose→ findings（可选；按 node_id 挂 node）
       ─render──→ facet 分派 → DisplayNode → text / html / treecli
跨 trace：corpus 把多个 node 树拍成三表 + 算子（contrast / signature / fleet）。
```

corpus parquet 走可选 extra `case-harness[trace-corpus]`（pyarrow），缺则 store 回退 jsonl。

## 关键约定

- **node 是分析本体，tree 退为视图期索引**：所有分析吃平 node 集，只在渲染等视图时刻才
  `ctx.view()` 现搭树；改分析逻辑不要去持树。
- **assemble 之后全是 structure-preserving**：只有 matches/claims 造结构（父子边）；其后 **feature(写
  facts) / diagnose(产 findings) / render(facet 出 DisplayNode)** 三步都只读树、各写自己那一层、
  **永不 re-parent**。三层同构：注册表 + 引擎，按 applies/match 分派（feature 用 pull+memo 自解依赖）。
- **业务知识只在 classify + build**：span 是哪种逻辑事件由 `spec.matches` 在 assemble 判（语义 kind
  不在采集层，NormSpan 无 kind 字段）；raw 的 `gen_ai.*` 等抽成命名 facts 锁死在 `KindSpec.build`——
  下游 feature/analyze/view/corpus 只见列名、零域知识。域专属 kind 随域包 `spec.merge` 叠加。
- **可机判的判读知识一律沉 detector（case as code）**：通用/整树判读走 `register_detector` 全局
  注册表（统一 `(node, ctx, found)` 签名、后序逐 node 跑、可读已产 findings 归因），kind 专属走
  `spec.rules`；内置拓扑(detached/obs_hole/propagated)也走注册表，不再硬编码。detector 每次 diagnose
  全量确定性召回，不靠文档被想起或检索命中；文档只留代码表达不了的 why（根因叙事、修复状态）。
- **view 渲染 signal-aware**：是否值得让人看某个 node，统一成 **signal**——biz 的**骨干/重要性**与
  diagnose 的 **finding（异常）都是 signal 的一种**。默认突出带 signal 的（骨干 + 问题），其余按 biz
  规则收缩（4k span 人只看二三十个；目标是价值不是减数）。signal 统一用**带 severity 的 Finding**表达
  （anomaly 走 warn/error；biz 骨干/重要性走 info，驱动 keep 但不刷问题清单）；`Aggregate`/`Group` 是
  biz 的折叠手柄、可展开虚拟节点，且**折叠对信号免疫**（≥error 自动浮出，绝不藏问题）。

## References

- 设计文档（理念/流程/决策记录）：[`../../docs/trace-harness.md`](../../docs/trace-harness.md)
- 工程约定（uv workspace、SDK 注册、lint）：上级 [`../AGENTS.md`](../AGENTS.md)
- 测试 fixture：`tests/fixtures/trace_genai_sample.jsonl`（真实 ES jaeger-span 形状）

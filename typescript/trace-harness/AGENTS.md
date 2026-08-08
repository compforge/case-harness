# TypeScript trace-harness

## 项目定位与边界

本包是 Trace Harness 规范的 TypeScript 实现，供 TypeScript 消费方在不依赖
Python runtime 的环境中完成 trace 建模与渲染。规范、IR schema 与共享 fixture
分别在 `../../spec/trace-harness.md`、`../../schema/trace/v1/` 和
`../../conformance/trace/`；Python 与 TypeScript 是对等实现。

## 代码地图与核心模块

目录沿用 `model → kinds → ingest → feature → analyze → view` 主链；新增公开概念时
先修改语言中立规范和 conformance case，再同步两端实现。

## 关键约定

1. `Node` 是分析本体，父子树只在 view 阶段构建。
2. 只有 `KindSpec.matches/claims` 改变结构；Feature、diagnose 和 render 不得 re-parent。
3. 通用包不写具体业务域知识；业务通过 scoped `TraceContributions` 贡献
   spec、Feature、Detector 和 Facet，不依赖模块导入副作用。Facet 只声明 brief/layout，
   不接管树递归和输出序列化。
4. Python 与 TypeScript 的公开 IR 字段保持同名，便于 fixture 与产物交叉验证。

## References

- `../../spec/trace-harness.md` — 语言中立规范
- `../../python/trace_harness/AGENTS.md` — Python 实现的代码地图与设计约定
- `../../docs/trace-harness.md` — trace-harness 设计文档

# TypeScript trace-harness

## 项目定位与边界

本包是 `python/trace_harness` 的 TypeScript 对齐实现，供 TypeScript 消费方在不依赖 Python
runtime 的环境中完成 trace 建模与渲染。概念、数据流和扩展边界以 Python 实现作为
canonical implementation。

## 代码地图与核心模块

目录沿用 Python 包的 `model → kinds → ingest → feature → analyze → view` 主链；新增能力时先在
Python canonical implementation 确认归属，再同步到对应 TypeScript 模块。

## 关键约定

1. `Node` 是分析本体，父子树只在 view 阶段构建。
2. 只有 `KindSpec.matches/claims` 改变结构；Feature、diagnose 和 render 不得 re-parent。
3. 通用包不写具体业务域知识；业务 spec、Feature 和 Facet 由消费方注册。
4. Python 与 TypeScript 的公开 IR 字段保持同名，便于 fixture 与产物交叉验证。

## References

- `../../python/trace_harness/AGENTS.md` — Python canonical implementation 的代码地图与设计约定
- `../../docs/trace-harness.md` — trace-harness 设计文档

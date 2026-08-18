# Backlog

## Trace tool command name：可选 Bash AST 解析

当前 Python 与 TypeScript trace-harness 使用轻量 tokenizer，从 tool arguments 中提取文件名或命令的语义短名，例如把一段较长的 shell command 展示为 `stream_query.py`。解析失败时回退到 tool name；该结果只影响 Node Tree、Agent Stack 与火焰图的展示，不参与安全判断或命令执行。

暂不引入 Baton 同类的 Bash AST 依赖：TypeScript 方案 `@lumis-sh/wasm-bash` + `web-tree-sitter` 约带来 1.3 MB grammar WASM 和 201 KB runtime WASM，Python 方案 `tree-sitter` + `tree-sitter-bash` 约带来 356 KB binding 和 1.44 MB grammar。相较仅用于展示的收益，当前包体、运行时初始化和双语言维护成本偏高。Baton 的 AST 用于只读命令判定，安全收益更直接，不宜机械照搬到展示层。

满足以下条件后再启动：

- pipeline、subshell、变量展开等复杂 command 已使轻量解析频繁产生误导性 name；
- 依赖可以限制在 trace-harness 包或可选 extra 内，不给其它 SDK 增重；
- Python 与 TypeScript 使用共享用例保证同一 command 产出一致的 name variants；
- AST 初始化或解析失败时仍可靠回退到 tool name。

候选实现分别为 Python 的 `tree-sitter` + `tree-sitter-bash`、TypeScript 的 `@lumis-sh/wasm-bash` + `web-tree-sitter`。落地前应先用真实 trace command corpus 衡量解析正确率与包体成本，再决定是否替换轻量 tokenizer。

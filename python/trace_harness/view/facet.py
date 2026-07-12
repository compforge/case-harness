"""Facet —— 某类 Node 的渲染策略（view 层）。

机制 vs biz：本模块只定义机制（Facet 协议、ChildOp、默认兜底 facet），**零 biz**——按
`agent_type` 之类 match 的具体 facet 由 skill（trace-as / trace-note）注册。

约束（与 IR 解耦的关键）：facet 只决定"本层怎么显示、孩子怎么摆"，**绝不改 Node 父子**；
能折叠 / 同父兄弟聚合 ×N / 子树摘要，不能 re-parent。match 只读 `node.facts`（kind、将来的
agent_type、cost…），不抠原生 span——facts 是 model↔view 唯一契约。

三档覆盖力度：
- 只覆盖 `brief`：换本行内容（多数 facet）。
- 再覆盖 `layout`：折叠 / 聚合 / 摘要孩子（结构型）。
- 覆盖 `render`：整片重画（如 workflow plan 的 group/step），少数。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from trace_harness.model.node import Field, Finding, Node

if TYPE_CHECKING:
    from trace_harness.model.viewtree import ViewTree
    from trace_harness.view.display import DisplayNode


# —— ChildOp：facet 对每个孩子声明的处置意图，由 engine 执行（facet 不自己递归）——


@dataclass
class Expand:
    """正常递归渲染这个子（默认）。"""

    node: Node


@dataclass
class Fold:
    """折叠这个子：不显示，但其子树 finding 会上浮到本节点；engine 把同父的 Fold 汇成一行摘要。"""

    node: Node


@dataclass
class Aggregate:
    """把一组**同父兄弟**聚成一行 ×N（不展开各自子树）。"""

    nodes: list[Node]
    label: str = ""


@dataclass
class Summarize:
    """把这个子的整棵子树压成一行自定义内容，不递归。"""

    node: Node
    line: list[Field]


@dataclass
class Hide:
    """折叠这个子：不显示、**也不出"… +N 折叠"摘要行**（信息已在父节点别处，如 http_status 已在
    model-call brief 上）。其子树 finding 仍上浮到最近可见祖先。与 Fold 的区别：Fold 留计数摘要、
    Hide 不留痕。"""

    node: Node


@dataclass
class Group:
    """把一组**连续同父兄弟**收成一个**命名虚拟概念**的合成行（`kind=""`）——biz 的折叠自定义手柄。

    与 Aggregate（"同类 ×N"、文案固定）的区别：成员可**异类**（如一个 turn =
    PLANNER+TOOL_EXEC+COMPRESSION），label/brief 自定义。成员渲进 DisplayNode.children，
    像真节点一样可展开/收缩：
    - `collapsed=True`：静态 md 只出摘要行、交互层（html/treecli）可展开（降 node 数）；
    - `collapsed=False`：默认展开（成员可见），用于"同概念但有信号要露出"的那个。

    成员经 `node_ids` 追踪（finding 上浮 / 展开）。虚拟概念只活在 view 层、不进 model.Node。"""

    nodes: list[Node]
    label: str
    brief: list[Field] = field(default_factory=list)
    collapsed: bool = True


ChildOp = Expand | Fold | Aggregate | Summarize | Hide | Group


@dataclass
class RenderConfig:
    """view 配方：同一 IR 换配方换形状（按行 / 按 service / 按 agent 压缩 = 不同配方）。"""

    prune_below_ms: float | None = None  # 给定则：耗时低于此、且子树无 finding/error 的孩子折叠
    max_depth: int | None = None
    expand: set[str] = field(default_factory=set)  # treecli：用户强制展开的 node_id


@dataclass
class RenderCtx:
    """engine 传给 facet 的只读上下文：结构 + 判读 + 配方。"""

    view: ViewTree
    findings: dict[str, list[Finding]]
    flagged: dict[str, bool]  # node_id → 子树是否含 finding/error（剪枝时必留）
    config: RenderConfig


class Facet:
    """渲染策略基类。子类至少实现 `match`；按需覆盖 brief / layout / render。"""

    priority: int = 0  # specificity：越大越先认领；同分按注册序

    def match(self, node: Node) -> bool:
        raise NotImplementedError

    def brief(self, node: Node) -> list[Field]:
        """本节点这一行的内容。默认 = assemble 期烤好的 ctx-free brief（IR 自洽兜底）。"""
        return node.brief

    def layout(self, node: Node, children: list[Node], rctx: RenderCtx) -> list[ChildOp]:
        """孩子布局。默认全展开。"""
        return [Expand(c) for c in children]

    def render(
        self,
        node: Node,
        children: list[Node],
        rctx: RenderCtx,
        recurse: Callable[[Node], DisplayNode],
    ) -> DisplayNode | None:
        """整片重画。默认返回 None → engine 用 brief+layout 标准组装。
        要自定义整片结构（合成分组头等）的 facet 才覆盖，并自行调 recurse 渲染想展开的子。"""
        return None


class DefaultFacet(Facet):
    """兜底 facet：读 node.brief + 按 prune_below_ms 折叠零碎子节点，对齐 callstack。"""

    priority = -(1 << 30)  # 永远最后兜底

    def match(self, node: Node) -> bool:
        return True

    def layout(self, node: Node, children: list[Node], rctx: RenderCtx) -> list[ChildOp]:
        cut = rctx.config.prune_below_ms
        if cut is None:
            return [Expand(c) for c in children]
        ops: list[ChildOp] = []
        for c in children:
            if c.duration_ms < cut and not rctx.flagged.get(c.node_id):
                ops.append(Fold(c))  # engine 把同父的 Fold 汇成一行折叠摘要
            else:
                ops.append(Expand(c))
        return ops

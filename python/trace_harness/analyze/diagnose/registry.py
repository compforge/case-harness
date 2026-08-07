"""全局 detector 注册表：不绑 kind、对每个 node 跑一遍（自 gate；trace 级在 root gate）。

与 per-kind `KindSpec.rules` 互补：rules 绑 kind、本表跨 kind（含整树/trace 级结论）。
签名 `(node, ctx, found) -> list[Finding]`：

- node 自带子树（`ctx.view().children`）→ trace 级 detector = 在 root/锚 node 上 gate、再顺子树扫；
  命不中的 node 第一行就 `return []`，避免 N× 重扫。
- `found` = 至此已产的 findings（dict[node_id, [Finding]]）；引擎**后序**跑（子先于父），
  故 detector 到某 node 时其子树 findings 已就绪，可挑进 `Finding.causes` 归因。多数忽略 found。

domain（AS）用 `register_detector(fn)` 注册。
"""

from __future__ import annotations

from collections.abc import Callable

from trace_harness.model.context import TraceContext
from trace_harness.model.node import Finding, Node

Detector = Callable[[Node, TraceContext, "dict[str, list[Finding]]"], list[Finding]]

_DETECTORS: list[Detector] = []


def register_detector(fn: Detector) -> Detector:
    """登记一个全局 detector，返回原对象（可作装饰器）。"""
    _DETECTORS.append(fn)
    return fn


def registered_detectors() -> list[Detector]:
    return list(_DETECTORS)

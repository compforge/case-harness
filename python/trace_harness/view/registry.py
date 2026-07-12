"""FacetRegistry —— 按 priority 分派 facet。

dispatch 取最高 priority 的 match；都不中 → DefaultFacet 兜底。skill 用 `register_facet`
在 import 时登记自己的 biz facet（像 framework 的 register_builder）。harness 自带的通用
facet 在 `view.facets` 里登记。
"""
from __future__ import annotations

from trace_harness.model.node import Node
from trace_harness.view.facet import DefaultFacet, Facet


class FacetRegistry:
    def __init__(self) -> None:
        self._facets: list[Facet] = []
        self._default = DefaultFacet()

    def register(self, facet: Facet) -> None:
        self._facets.append(facet)
        # 稳定排序：priority 降序，同分保留注册先后（list.sort 稳定）
        self._facets.sort(key=lambda f: -f.priority)

    def dispatch(self, node: Node) -> Facet:
        for f in self._facets:
            if f.match(node):
                return f
        return self._default


DEFAULT_REGISTRY = FacetRegistry()


def register_facet(facet: Facet) -> Facet:
    """登记到默认注册表，返回原对象（可作装饰器/直接调用）。"""
    DEFAULT_REGISTRY.register(facet)
    return facet

"""Feature 注册表 —— harness 自带在 `feature.builtins` 登记，biz（AS 等）自行 `register_feature`。

`producing(name, node)` 找产某个名、且 applies 这个 node 的 Feature（pull 时由 Ctx 调）。
"""
from __future__ import annotations

from trace_harness.feature.feature import Feature
from trace_harness.model.node import Node

_REGISTRY: list[Feature] = []


def register_feature(f: Feature) -> Feature:
    _REGISTRY.append(f)
    return f


def registered_features() -> list[Feature]:
    return list(_REGISTRY)


def producing(name: str, node: Node) -> Feature | None:
    for f in _REGISTRY:
        if name in f.produces and f.applies(node):
            return f
    return None

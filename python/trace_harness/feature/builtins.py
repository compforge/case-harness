"""harness 自带 Feature —— import 即登记。零 biz；biz（按 agent_type、curl 等）由 skill 自行登记。

都是 eager（bake=True）+ 读 facts/结构（不读 raw），故 IR-portable。
"""
from __future__ import annotations

from trace_harness.feature.ctx import Ctx
from trace_harness.feature.feature import Feature
from trace_harness.feature.registry import register_feature
from trace_harness.model.intervals import interval_union
from trace_harness.model.node import Node


def _self_ms(node: Node, ctx: Ctx) -> dict:
    """self_ms = 本节点墙钟 − 子区间并集（未被子覆盖的独占耗时）。叶子不写。"""
    children = ctx.children(node)
    if not children:
        return {}
    covered = interval_union([(c.start_ms, c.end_ms) for c in children])
    return {"self_ms": round(max(0.0, node.duration_ms - covered), 3)}


def _http_status(node: Node, ctx: Ctx) -> dict:
    """model-call 从 http 子卷 http_status；非 200 优先（重试时成功那次会掩盖失败）。"""
    stats = [ctx.get(c, "status") for c in ctx.children(node) if c.kind == "http"]
    stats = [int(s) for s in stats if s is not None]
    if not stats:
        return {}
    return {"http_status": next((s for s in stats if s != 200), stats[0])}


register_feature(Feature(("self_ms",), lambda n: True, _self_ms, bake=True))
register_feature(
    Feature(("http_status",), lambda n: n.kind == "model-call", _http_status, bake=True)
)

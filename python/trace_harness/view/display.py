"""DisplayNode —— 渲染产物：一棵脱离 ctx/kind 的显示树。

facet 不拼字符串、不碰格式：它只产出结构化的 DisplayNode（本行 = kind/name/brief，
加 engine 绑上来的 findings），由序列化器（text/markdown/html/treecli）各自成文。一个 facet
也可以产出**合成节点**（kind="" 的 collapse 行 / plan 分组头）——没有对应 Node 时 node_ids 为空。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from trace_harness.model.node import Field, Finding


class CompactName(Protocol):
    """Presentation object that owns names from highest to lowest fidelity."""

    def name_variants(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class DisplayName:
    name: str
    detail: str = ""

    def name_variants(self) -> tuple[str, ...]:
        if not self.detail:
            return (self.name,)
        return f"{self.name} · {self.detail}", self.detail, self.name


def name_variants(named: CompactName) -> list[str]:
    """Serialize compact names for renderers whose budget is known only at runtime."""
    return list(named.name_variants())


@dataclass
class DisplayNode:
    kind: str  # "" = 合成行（折叠摘要 / 分组头），序列化时不打 `name` 反引号
    name: str
    brief: list[Field] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)  # 本行代表的 Node；合成行为空，聚合行为 N 个
    children: list[DisplayNode] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)  # engine 按 node_id 绑定（含上浮的）
    folded: int = 0  # 本行折叠/聚合掉多少个原生 Node（× N / rollup 提示）
    display_name: DisplayName | None = None

    def name_variants(self) -> tuple[str, ...]:
        return (self.display_name or DisplayName(self.name)).name_variants()

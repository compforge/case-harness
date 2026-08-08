"""trace_harness —— e2e-harness 的第四个 SDK：trace/span 分析框架。

前三个 harness 把系统当黑盒（发请求看响应），trace_harness 开盒：消费请求留下的遥测
（OTel/Jaeger span），回答"链路内部哪一层先反常"。设计见 docs/trace-harness.md。

核心立场（与 Canopy 同构）：raw span 是物理事实，**逻辑事件 node 是分析本体**，
特征列 facts/findings 是分析底座；"树"只是看单条 trace 时的视图，不是中心对象。

公共 API 从包根导入（``from trace_harness import build_context, render_text``）；
内部模块布局可能变动，包根名是稳定面。
"""

from __future__ import annotations

from trace_harness.harness import TraceContributions as TraceContributions
from trace_harness.harness import TraceHarness as TraceHarness
from trace_harness.harness import contributions_from_specs as contributions_from_specs
from trace_harness.harness import merge_trace_contributions as merge_trace_contributions
from trace_harness.ingest.assemble import assemble as assemble
from trace_harness.ingest.load import build_context as build_context
from trace_harness.ingest.sources.jaeger_file import load_jaeger_file as load_jaeger_file
from trace_harness.model.analysis import analysis_snapshot as analysis_snapshot
from trace_harness.model.context import TraceContext as TraceContext
from trace_harness.model.ir import TraceView as TraceView
from trace_harness.model.ir import dump_view as dump_view
from trace_harness.model.ir import load_view as load_view
from trace_harness.model.node import Finding as Finding
from trace_harness.model.node import Node as Node
from trace_harness.model.span import NormSpan as NormSpan
from trace_harness.model.spec import KindSpec as KindSpec
from trace_harness.model.spec import SpecSet as SpecSet
from trace_harness.model.spec import merge as merge
from trace_harness.view.explore import render_explore as render_explore
from trace_harness.view.text import render_text as render_text

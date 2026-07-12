"""feature —— 特征层：从 node 算命名值。统一了 build(eager+raw) / derive(eager+facts) /
repro(lazy)，全是 `Feature` 在 (bake × 读raw) 平面上的点（见 feature.py）。

import 即登记 harness 自带 Feature；biz（AS 的 agent_type / curl…）自行 `register_feature`。
"""
from __future__ import annotations

from trace_harness.feature import builtins as _builtins  # noqa: F401 —— import 即登记
from trace_harness.feature.ctx import Ctx as Ctx
from trace_harness.feature.engine import bake_features as bake_features
from trace_harness.feature.engine import lazy_features as lazy_features
from trace_harness.feature.feature import Feature as Feature
from trace_harness.feature.registry import register_feature as register_feature
from trace_harness.feature.registry import registered_features as registered_features

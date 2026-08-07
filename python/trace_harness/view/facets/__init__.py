"""harness 自带通用 facet —— import 即登记进 DEFAULT_REGISTRY。零 biz。

DefaultFacet 是注册表内置兜底（在 registry 里直接持有，不在此登记）。这里登记需要
"按 kind/特征抢在默认之前"的通用 facet。biz facet（按 agent_type 等）由 skill 注册。
"""

from trace_harness.view.facets.model_call import ModelCallFacet
from trace_harness.view.facets.service import ServiceFacet
from trace_harness.view.registry import register_facet

register_facet(ServiceFacet())
register_facet(ModelCallFacet())

"""AgentRun IR extraction and generic rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trace_harness import (
    AgentRun,
    AgentRunIR,
    AgentTurn,
    ModelCall,
    Operation,
    ToolCall,
    TraceContributions,
    TraceHarness,
    agent_run_snapshot,
)
from trace_harness.ingest.sources.jaeger_file import load_jaeger_file
from trace_harness.kinds import genai

ROOT = Path(__file__).parents[3]
RAW = ROOT / "conformance" / "trace" / "fixtures" / "genai-basic.jsonl"
EXPECTED = ROOT / "conformance" / "trace" / "cases" / "genai-basic.agent-run.json"


class _FixtureAgentRunExtractor:
    """Sanitized business extraction rule used only by the shared conformance case."""

    def extract(self, context):
        by_name = {node.name: node for node in context.nodes}
        agent = by_name["invoke_agent main"]
        planner = by_name["chat planner"]
        tool = by_name["execute_tool web_search"]
        synth = by_name["chat synth"]
        return AgentRunIR(
            trace_id=context.trace_id,
            runs=(
                AgentRun(
                    id="run-main",
                    name="main-agent",
                    start_ms=agent.start_ms,
                    duration_ms=agent.duration_ms,
                    status="error",
                    source_node_ids=(agent.node_id,),
                    items=(
                        Operation(
                            id="initialize-1",
                            name="run.initialize",
                            start_ms=agent.start_ms,
                            duration_ms=100,
                            status="completed",
                            source_node_ids=(agent.node_id,),
                        ),
                        AgentTurn(
                            id="turn-plan",
                            name="Plan and search",
                            start_ms=planner.start_ms,
                            duration_ms=4750,
                            items=(
                                ModelCall(
                                    id="model-plan",
                                    name="planner",
                                    model="model-alpha-seed-2",
                                    start_ms=planner.start_ms,
                                    duration_ms=planner.duration_ms,
                                    status="completed",
                                    input=[{"role": "user", "content": "Find a source"}],
                                    output={"tool_calls": [{"name": "web_search"}]},
                                    attributes={"input_tokens": 1820, "output_tokens": 640},
                                    source_node_ids=(planner.node_id,),
                                ),
                                ToolCall(
                                    id="tool-search",
                                    name="web_search",
                                    tool_call_id="call-search-1",
                                    start_ms=tool.start_ms,
                                    duration_ms=tool.duration_ms,
                                    status="completed",
                                    input={"query": "example"},
                                    output={"matches": 1},
                                    source_node_ids=(tool.node_id,),
                                ),
                                Operation(
                                    id="compact-1",
                                    name="context.compact",
                                    start_ms=1700000004800,
                                    duration_ms=50,
                                    status="completed",
                                    input={"messages": 12},
                                    output={"messages": 4},
                                    source_node_ids=(agent.node_id,),
                                ),
                            ),
                        ),
                        Operation(
                            id="checkpoint-1",
                            name="framework.checkpoint",
                            start_ms=1700000004850,
                            duration_ms=25,
                            status="completed",
                            source_node_ids=(agent.node_id,),
                        ),
                        AgentTurn(
                            id="turn-answer",
                            name="Answer",
                            start_ms=1700000004875,
                            duration_ms=2525,
                            items=(
                                Operation(
                                    id="wrap-up-1",
                                    name="turn.wrap_up",
                                    start_ms=1700000004875,
                                    duration_ms=25,
                                    status="completed",
                                    source_node_ids=(agent.node_id,),
                                ),
                                ModelCall(
                                    id="model-answer",
                                    name="synthesizer",
                                    model="model-alpha-seed-2",
                                    start_ms=synth.start_ms,
                                    duration_ms=synth.duration_ms,
                                    status="error",
                                    input=[{"role": "user", "content": "Answer with the source"}],
                                    source_node_ids=(synth.node_id,),
                                ),
                            ),
                        ),
                        Operation(
                            id="finalize-1",
                            name="run.finalize",
                            start_ms=1700000007400,
                            duration_ms=600,
                            status="completed",
                            source_node_ids=(agent.node_id,),
                        ),
                    ),
                ),
            ),
        )


def _harness(extractor=None):
    return TraceHarness(
        TraceContributions(
            specs=tuple(genai.specs()),
            agent_run_extractor=extractor,
        )
    )


def test_agent_run_ir_matches_shared_conformance_case():
    harness = _harness(_FixtureAgentRunExtractor())
    context = harness.assemble(load_jaeger_file(RAW))

    actual = harness.extract_agent_runs(context)

    assert actual is not None
    assert agent_run_snapshot(actual) == json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_interactive_agent_view_is_owned_by_agent_run_renderer():
    harness = _harness(_FixtureAgentRunExtractor())
    context = harness.assemble(load_jaeger_file(RAW))

    html = harness.render_interactive(context, harness.diagnose(context))

    assert 'data-perspective="agent"' in html
    assert "agent-run:run-main" in html
    assert "run.initialize" in html
    assert "context.compact" in html
    assert "turn.wrap_up" in html
    assert "framework.checkpoint" in html
    assert "run.finalize" in html
    assert "tool-search" in html


def test_interactive_hides_agent_view_without_an_extractor():
    harness = _harness()
    context = harness.assemble(load_jaeger_file(RAW))

    assert 'data-perspective="agent"' not in harness.render_interactive(context)


def test_extractor_output_rejects_unknown_node_references():
    class BrokenExtractor:
        def extract(self, context):
            return AgentRunIR(
                trace_id=context.trace_id,
                runs=(
                    AgentRun(
                        id="broken",
                        name="broken",
                        start_ms=0,
                        duration_ms=0,
                        source_node_ids=("missing-node",),
                        items=(),
                    ),
                ),
            )

    harness = _harness(BrokenExtractor())
    context = harness.assemble(load_jaeger_file(RAW))

    with pytest.raises(ValueError, match="unknown node IDs"):
        harness.extract_agent_runs(context)

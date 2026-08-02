from __future__ import annotations

import json

from trajectory_harness.loaders.otel_json import OTelJsonLoader


def _attr(key, value):
    if isinstance(value, int):
        wrapped = {"intValue": str(value)}
    else:
        wrapped = {"stringValue": value}
    return {"key": key, "value": wrapped}


def test_loads_ordered_genai_steps_and_synthesizes_tool_messages(tmp_path):
    output_messages = [
        {
            "role": "assistant",
            "parts": [
                {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "file_read",
                    "arguments": {"path": "a.go"},
                }
            ],
            "finish_reason": "tool_calls",
        }
    ]
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "reviewer")]},
                "scopeSpans": [
                    {
                        "scope": {"name": "agentgo", "version": "0.1.0"},
                        "spans": [
                            {
                                "traceId": "trace-1",
                                "spanId": "model-1",
                                "name": "chat model-a",
                                "startTimeUnixNano": "1000000",
                                "endTimeUnixNano": "3000000",
                                "attributes": [
                                    _attr("gen_ai.operation.name", "chat"),
                                    _attr(
                                        "gen_ai.output.messages",
                                        json.dumps(output_messages),
                                    ),
                                ],
                            },
                            {
                                "traceId": "trace-1",
                                "spanId": "tool-1",
                                "parentSpanId": "model-1",
                                "name": "execute_tool file_read",
                                "startTimeUnixNano": "4000000",
                                "endTimeUnixNano": "7000000",
                                "attributes": [
                                    _attr("gen_ai.operation.name", "execute_tool"),
                                    _attr("gen_ai.tool.name", "file_read"),
                                    _attr("gen_ai.tool.call.id", "call-1"),
                                    _attr(
                                        "gen_ai.tool.call.arguments",
                                        json.dumps({"path": "a.go"}),
                                    ),
                                    _attr("gen_ai.tool.call.result", "package a"),
                                ],
                                "status": {"code": "STATUS_CODE_OK"},
                            },
                        ],
                    }
                ],
            }
        ]
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    trajectories = OTelJsonLoader().load(path)

    assert len(trajectories) == 1
    trajectory = trajectories[0]
    assert trajectory.trajectory_id == "trace-1"
    assert [step.step_id for step in trajectory.steps] == ["model-1", "tool-1"]
    tool = trajectory.steps[1]
    assert tool.parent_step_id == "model-1"
    assert tool.name == "file_read"
    assert tool.status == "ok"
    assert tool.duration_ms == 3
    assert tool.input_messages[0]["parts"][0]["arguments"] == {"path": "a.go"}
    assert tool.output_messages[0]["parts"][0]["response"] == "package a"
    assert tool.attributes["service.name"] == "reviewer"
    assert tool.attributes["otel.scope.name"] == "agentgo"


def test_promotes_message_attributes_from_events(tmp_path):
    messages = [{"role": "assistant", "parts": [{"type": "text", "content": "done"}]}]
    path = tmp_path / "trace.jsonl"
    path.write_text(
        json.dumps(
            {
                "traceId": "trace-1",
                "spanId": "model-1",
                "name": "chat",
                "startTimeUnixNano": "0",
                "endTimeUnixNano": "1",
                "attributes": [_attr("gen_ai.operation.name", "chat")],
                "events": [
                    {
                        "attributes": [
                            _attr("gen_ai.output.messages", json.dumps(messages))
                        ]
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    trajectory = OTelJsonLoader().load(path)[0]

    assert trajectory.steps[0].output_messages[0]["parts"][0]["content"] == "done"

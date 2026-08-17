import type { AgentRunIR, AgentTurn, TurnItem } from "../model/agent";
import type { TraceContext } from "../model/context";
import type { Finding, Node } from "../model/node";

function text(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function sourcePayload(
  context: TraceContext,
  sourceNodeIds: string[] = [],
  findings: Record<string, Finding[]>,
  status = "",
): Record<string, unknown> {
  const nodes = sourceNodeIds
    .map((nodeId) => context.view().by_id.get(nodeId))
    .filter((node): node is Node => Boolean(node));
  const spanIds = [...new Set(nodes.flatMap((node) => node.span_ids))];
  const errorSpanIds = [...new Set(nodes.flatMap((node) => node.error_span_ids))];
  const statusError = ["error", "failed", "failure"].includes(status.toLowerCase());
  return {
    service: nodes[0]?.service ?? "",
    has_error: errorSpanIds.length > 0 || statusError,
    error: errorSpanIds.length ? context.error_text(errorSpanIds[0]!) : status,
    findings: nodes.flatMap((node) => (findings[node.node_id] ?? []).map((finding) => ({
      severity: finding.severity,
      source: finding.source,
      note: finding.note ?? "",
    }))),
    span_ids: spanIds,
    primary_span_id: nodes[0]?.primary_span_id ?? "",
    error_span_ids: errorSpanIds,
  };
}

function facts(
  status = "",
  attributes: Record<string, unknown> = {},
  sourceNodeIds: string[] = [],
): Record<string, string> {
  const values = Object.fromEntries(Object.entries(attributes).map(([key, value]) => [key, text(value)]));
  if (status) values.status = status;
  if (sourceNodeIds.length) values.source_nodes = sourceNodeIds.join(", ");
  return values;
}

function itemPayload(
  context: TraceContext,
  item: TurnItem,
  findings: Record<string, Finding[]>,
): Record<string, unknown> {
  const itemFacts = facts(item.status, item.attributes, item.source_node_ids);
  let brief = "";
  if (item.kind === "model-call" && item.model) {
    itemFacts.model = item.model;
    brief = `model=${item.model}`;
  } else if (item.kind === "tool-call" && item.tool_call_id) {
    itemFacts.tool_call_id = item.tool_call_id;
    brief = `call=${item.tool_call_id}`;
  }
  return {
    node_id: `agent-item:${item.kind}:${item.id}`,
    kind: item.kind,
    name: item.name,
    start_ms: item.start_ms,
    duration_ms: item.duration_ms,
    brief,
    facts: itemFacts,
    features: Object.fromEntries([
      ...(item.input === undefined ? [] : [["input", text(item.input)]]),
      ...(item.output === undefined ? [] : [["output", text(item.output)]]),
    ]),
    folded: 0,
    children: [],
    ...sourcePayload(context, item.source_node_ids, findings, item.status),
  };
}

function turnPayload(
  context: TraceContext,
  turn: AgentTurn,
  index: number,
  findings: Record<string, Finding[]>,
): Record<string, unknown> {
  const children = turn.items.map((item) => itemPayload(context, item, findings));
  const sources = turn.source_node_ids ?? [...new Set(turn.items.flatMap((item) => item.source_node_ids ?? []))];
  return {
    node_id: `agent-turn:${turn.id}`,
    kind: "agent-turn",
    name: turn.name || `Turn ${index + 1}`,
    start_ms: turn.start_ms,
    duration_ms: turn.duration_ms,
    brief: `${turn.items.length} items`,
    facts: facts(turn.status, turn.attributes, sources),
    features: {},
    folded: 0,
    children,
    ...sourcePayload(context, sources, findings, turn.status),
  };
}

export function agentRunRoots(
  context: TraceContext,
  ir: AgentRunIR,
  findings: Record<string, Finding[]>,
): Array<Record<string, unknown>> {
  return ir.runs.map((run) => {
    let turnIndex = 0;
    const children = run.items.map((item) => {
      if (item.kind === "operation") return itemPayload(context, item, findings);
      const payload = turnPayload(context, item, turnIndex, findings);
      turnIndex += 1;
      return payload;
    });
    const sources = run.source_node_ids ?? [...new Set(run.items.flatMap((item) => (
      item.kind === "operation"
        ? item.source_node_ids ?? []
        : item.items.flatMap((turnItem) => turnItem.source_node_ids ?? [])
    )))];
    const operationCount = run.items.filter((item) => item.kind === "operation").length;
    return {
      node_id: `agent-run:${run.id}`,
      kind: "agent-run",
      name: run.name,
      start_ms: run.start_ms,
      duration_ms: run.duration_ms,
      brief: `${turnIndex} turns · ${operationCount} operations`,
      facts: facts(run.status, run.attributes, sources),
      features: {},
      folded: 0,
      children,
      ...sourcePayload(context, sources, findings, run.status),
    };
  });
}

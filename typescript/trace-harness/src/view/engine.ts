import "./facets";

import { formatMs } from "../kinds/base";
import type { Finding, Node } from "../model/node";
import type { ViewTree } from "../model/viewtree";
import type { DisplayNode } from "./display";
import type { ChildOp, RenderConfig, RenderContext } from "./facet";
import { DEFAULT_REGISTRY, type FacetRegistry } from "./registry";

function subtreeSize(view: ViewTree, node: Node): { count: number; total: number } {
  let count = 1;
  let total = node.duration_ms;
  for (const child of view.children(node)) {
    const nested = subtreeSize(view, child);
    count += nested.count;
    total += nested.total;
  }
  return { count, total };
}

function flagged(view: ViewTree, findings: Record<string, Finding[]>): Map<string, boolean> {
  const result = new Map<string, boolean>();
  const mark = (node: Node): boolean => {
    let value = node.has_error || Boolean(findings[node.node_id]?.length);
    for (const child of view.children(node)) value = mark(child) || value;
    result.set(node.node_id, value);
    return value;
  };
  for (const root of view.roots) mark(root);
  return result;
}

function synthetic(name: string, nodeIds: string[], folded: number): DisplayNode {
  return { kind: "", name, brief: [], node_ids: nodeIds, children: [], findings: [], folded };
}

function foldedLine(view: ViewTree, nodes: Node[], cut: number): DisplayNode {
  const values = nodes.map((node) => subtreeSize(view, node));
  const count = values.reduce((sum, value) => sum + value.count, 0);
  const total = nodes.reduce((sum, node) => sum + node.duration_ms, 0);
  return synthetic(`… +${count} 个小节点折叠（<${formatMs(cut)}，sum ${formatMs(total)}）`, nodes.map((node) => node.node_id), count);
}

export function renderDisplay(
  view: ViewTree,
  findings: Record<string, Finding[]> = {},
  registry: FacetRegistry = DEFAULT_REGISTRY,
  config: RenderConfig = {},
): DisplayNode[] {
  const context: RenderContext = {
    view,
    findings,
    flagged: config.prune_below_ms === undefined ? new Map() : flagged(view, findings),
    config,
  };
  const visible = new Map<string, DisplayNode>();

  const renderNode = (node: Node): DisplayNode => {
    const facet = registry.dispatch(node);
    const children = view.children(node);
    const custom = facet.render(node, children, context, renderNode);
    if (custom) {
      for (const nodeId of custom.node_ids) if (!visible.has(nodeId)) visible.set(nodeId, custom);
      return custom;
    }
    const output: DisplayNode[] = [];
    const folded: Node[] = [];
    for (const operation of facet.layout(node, children, context)) {
      switch (operation.type) {
        case "expand": output.push(renderNode(operation.node)); break;
        case "fold": folded.push(operation.node); break;
        case "hide": break;
        case "summarize":
          output.push({
            kind: operation.node.kind,
            name: operation.node.name,
            brief: operation.line,
            node_ids: [operation.node.node_id],
            children: [], findings: [], folded: 0,
          });
          break;
        case "aggregate": {
          const total = operation.nodes.reduce((sum, item) => sum + item.duration_ms, 0);
          const line = synthetic(
            `${operation.label ?? operation.nodes[0]?.kind ?? ""} ×${operation.nodes.length}（sum ${formatMs(total)}）`,
            operation.nodes.map((item) => item.node_id),
            operation.nodes.length,
          );
          line.children = operation.nodes.map(renderNode);
          output.push(line);
          break;
        }
        case "group": {
          const isFolded = operation.collapsed !== false;
          const count = isFolded
            ? operation.nodes.reduce((sum, item) => sum + subtreeSize(view, item).count, 0)
            : 0;
          const line = synthetic(operation.label, operation.nodes.map((item) => item.node_id), count);
          line.brief = operation.brief ?? [];
          line.children = operation.nodes.map(renderNode);
          output.push(line);
          break;
        }
      }
    }
    if (folded.length) output.push(foldedLine(view, folded, config.prune_below_ms!));
    const display: DisplayNode = {
      kind: node.kind,
      name: node.name,
      brief: facet.brief(node),
      node_ids: [node.node_id],
      children: output,
      findings: [],
      folded: 0,
    };
    visible.set(node.node_id, display);
    return display;
  };

  const roots = view.roots.map(renderNode);
  for (const [nodeId, nodeFindings] of Object.entries(findings)) {
    if (!nodeFindings.length) continue;
    let target = visible.get(nodeId);
    let node = view.by_id.get(nodeId);
    while (!target && node?.parent_node_id) {
      node = view.by_id.get(node.parent_node_id);
      target = node ? visible.get(node.node_id) : undefined;
    }
    target?.findings.push(...nodeFindings);
  }
  return roots;
}

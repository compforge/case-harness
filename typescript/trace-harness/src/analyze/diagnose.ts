import type { TraceContext } from "../model/context";
import type { Finding } from "../model/node";

export type Findings = Record<string, Finding[]>;

function append(findings: Findings, finding: Finding): void {
  if (!finding.ref) return;
  (findings[finding.ref] ??= []).push(finding);
}

/** Python diagnose 主链的 node-scope 子集：物理错误 + per-kind rules。 */
export function diagnose(context: TraceContext): Findings {
  const findings: Findings = {};
  for (const node of context.nodes) {
    if (node.has_error) {
      append(findings, {
        ref: node.node_id,
        source: "error",
        severity: "error",
        note: node.error_text,
      });
    }
    for (const rule of context.specs.get(node.kind)?.rules ?? []) {
      for (const finding of rule(node, context)) append(findings, finding);
    }
  }
  return findings;
}

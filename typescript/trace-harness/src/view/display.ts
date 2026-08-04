import type { Field, Finding } from "../model/node";

export interface DisplayNode {
  kind: string;
  name: string;
  brief: Field[];
  node_ids: string[];
  children: DisplayNode[];
  findings: Finding[];
  folded: number;
}

import type { Field, Finding } from "../model/node";

export interface CompactName {
  nameVariants(): readonly string[];
}

export class DisplayName implements CompactName {
  constructor(
    readonly name: string,
    readonly detail = "",
  ) {}

  nameVariants(): readonly string[] {
    return this.detail
      ? [`${this.name} · ${this.detail}`, this.detail, this.name]
      : [this.name];
  }
}

export interface DisplayNode extends Partial<CompactName> {
  kind: string;
  name: string;
  display_name?: DisplayName;
  brief: Field[];
  node_ids: string[];
  children: DisplayNode[];
  findings: Finding[];
  folded: number;
}

export function nameVariants(named: DisplayNode | CompactName): string[] {
  if (named.nameVariants) return [...named.nameVariants()];
  const display = named as DisplayNode;
  return [...(display.display_name ?? new DisplayName(display.name)).nameVariants()];
}

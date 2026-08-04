import type { Node } from "../model/node";
import { buildView, type ViewTree } from "../model/viewtree";
import { FeatureContext } from "./context";
import { registeredFeatures } from "./registry";

export function bakeFeatures(
  nodes: Node[],
  raw?: (spanId: string) => Record<string, unknown>,
): void {
  const context = new FeatureContext(buildView(nodes), raw);
  const eager = registeredFeatures().filter((feature) => feature.bake !== false);
  for (const node of nodes) {
    for (const feature of eager) {
      if (!feature.applies(node)) continue;
      for (const name of feature.produces) {
        const value = context.get(node, name);
        if (value !== undefined) node.facts[name] = value;
      }
    }
  }
}

export function lazyFeatures(
  node: Node,
  view: ViewTree,
  raw?: (spanId: string) => Record<string, unknown>,
): Record<string, unknown> {
  const context = new FeatureContext(view, raw);
  const output: Record<string, unknown> = {};
  for (const feature of registeredFeatures()) {
    if (feature.bake !== false || !feature.applies(node)) continue;
    for (const name of feature.produces) output[name] = context.get(node, name);
  }
  return output;
}

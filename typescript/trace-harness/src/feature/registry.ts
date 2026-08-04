import type { Node } from "../model/node";
import type { Feature } from "./feature";

const FEATURES: Feature[] = [];

export function registerFeature(feature: Feature): Feature {
  FEATURES.push(feature);
  return feature;
}

export function registeredFeatures(): Feature[] {
  return [...FEATURES];
}

export function producing(name: string, node: Node): Feature | undefined {
  return FEATURES.find((feature) => feature.produces.includes(name) && feature.applies(node));
}

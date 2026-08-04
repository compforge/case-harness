import type { Node } from "../model/node";
import { DefaultFacet, type Facet } from "./facet";

export class FacetRegistry {
  readonly #facets: Facet[] = [];
  readonly #default = new DefaultFacet();

  register(facet: Facet): void {
    this.#facets.push(facet);
    this.#facets.sort((a, b) => b.priority - a.priority);
  }

  dispatch(node: Node): Facet {
    return this.#facets.find((facet) => facet.match(node)) ?? this.#default;
  }
}

export const DEFAULT_REGISTRY = new FacetRegistry();

export function registerFacet(facet: Facet): Facet {
  DEFAULT_REGISTRY.register(facet);
  return facet;
}

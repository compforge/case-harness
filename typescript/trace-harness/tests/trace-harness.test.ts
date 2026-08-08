import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  analysisSnapshot,
  assemble,
  DefaultFacet,
  diagnose,
  type FeatureContext,
  genAiSpecs,
  Node,
  normalizeJaegerSpans,
  renderInteractive,
  TraceHarness,
} from "../src";

function fixtureDocuments(): Array<Record<string, unknown>> {
  const path = resolve(import.meta.dir, "../../../conformance/trace/fixtures/genai-basic.jsonl");
  return readFileSync(path, "utf8").trim().split("\n").map((line) => JSON.parse(line));
}

describe("Python trace_harness parity fixture", () => {
  test("normalizes and assembles the same logical node set", () => {
    const context = assemble(normalizeJaegerSpans(fixtureDocuments()), genAiSpecs());
    expect(context.trace_id).toBe("abc123fixturetrace0000000000000001");
    expect(context.spans.size).toBe(6);
    expect(context.nodes
      .sort((a, b) => a.start_ms - b.start_ms)
      .map((node) => [node.kind, node.name, node.parent_node_id ?? null]))
      .toEqual([
        ["agent", "invoke_agent main", null],
        ["model-call", "chat planner", "1111111111111111"],
        ["http", "POST /chat/completions", "2222222222222222"],
        ["tool-call", "execute_tool web_search", "1111111111111111"],
        ["model-call", "chat synth", "1111111111111111"],
        ["http", "POST /chat/completions", "5555555555555555"],
      ]);
    const planner = context.nodes.find((node) => node.name === "chat planner")!;
    expect(planner.facts).toMatchObject({
      model: "model-alpha-seed-2",
      in_tokens: 1820,
      out_tokens: 640,
      self_ms: 100,
      http_status: 200,
    });
  });

  test("renders the Python interactive view contract as one HTML file", () => {
    const context = assemble(normalizeJaegerSpans(fixtureDocuments()), genAiSpecs());
    const html = renderInteractive(context, diagnose(context));
    expect(html).toStartWith("<!doctype html>");
    expect(html).toContain("调用栈");
    expect(html).toContain("火焰图");
    expect(html).toContain("chat planner");
    expect(html).toContain("http_status");
    expect(html).toContain("errors 2");
  });
});

describe("shared conformance", () => {
  test("matches the canonical Analysis IR", async () => {
    const expected = await Bun.file(new URL(
      "../../../conformance/trace/cases/genai-basic.analysis.json",
      import.meta.url,
    )).json();
    const harness = new TraceHarness({ specs: genAiSpecs() });
    const context = harness.assemble(normalizeJaegerSpans(fixtureDocuments()));

    expect(analysisSnapshot(context, harness.diagnose(context))).toEqual(expected);
  });
});

describe("scoped TraceHarness", () => {
  test("does not leak Plugin contributions between harnesses", () => {
    class AlphaModelFacet extends DefaultFacet {
      override priority = 100;
      match(node: Node): boolean {
        return node.kind === "model-call";
      }
    }

    const alpha = new TraceHarness({
      specs: genAiSpecs(),
      features: [{
        produces: ["scope_marker"],
        applies: (node) => node.kind === "agent",
        compute: () => ({ scope_marker: "alpha" }),
        bake: true,
      }, {
        produces: ["scope_action"],
        applies: (node) => node.kind === "agent",
        compute: (_node: Node, _context: FeatureContext) => ({ scope_action: "alpha-action" }),
        bake: false,
      }],
      detectors: [(node) => node.facts.scope_marker === "alpha" ? [{
        ref: node.node_id,
        source: "scope:alpha",
        severity: "info",
      }] : []],
      facets: [new AlphaModelFacet()],
    });
    const plain = new TraceHarness({ specs: genAiSpecs() });

    const alphaContext = alpha.assemble(normalizeJaegerSpans(fixtureDocuments()));
    const plainContext = plain.assemble(normalizeJaegerSpans(fixtureDocuments()));
    const alphaAgent = alphaContext.nodes.find((node) => node.kind === "agent")!;
    const plainAgent = plainContext.nodes.find((node) => node.kind === "agent")!;

    expect(alphaAgent.facts.scope_marker).toBe("alpha");
    expect(plainAgent.facts.scope_marker).toBeUndefined();
    expect(alpha.lazyFeatures(alphaAgent, alphaContext)).toEqual({ scope_action: "alpha-action" });
    expect(plain.lazyFeatures(plainAgent, plainContext)).toEqual({});
    const alphaFindings = alpha.diagnose(alphaContext);
    const plainFindings = plain.diagnose(plainContext);
    expect(alphaFindings[alphaAgent.node_id]?.map((finding) => finding.source))
      .toContain("scope:alpha");
    expect(Object.values(plainFindings).flat().map((finding) => finding.source))
      .not.toContain("scope:alpha");
    const displayedIds = (roots: ReturnType<TraceHarness["renderDisplay"]>): Set<string> => {
      const ids = new Set<string>();
      const stack = [...roots];
      while (stack.length) {
        const display = stack.pop()!;
        if (display.kind) for (const nodeId of display.node_ids) ids.add(nodeId);
        stack.push(...display.children);
      }
      return ids;
    };
    const successHttp = alphaContext.nodes.find((node) => (
      node.kind === "http" && node.facts.status === 200
    ))!;
    expect(displayedIds(alpha.renderDisplay(alphaContext, alphaFindings))).toContain(successHttp.node_id);
    expect(displayedIds(plain.renderDisplay(plainContext, plainFindings))).not.toContain(successHttp.node_id);
    expect(alpha.renderInteractive(alphaContext, alphaFindings)).toContain("alpha-action");
    expect(plain.renderInteractive(plainContext, plainFindings)).not.toContain("alpha-action");
  });
});

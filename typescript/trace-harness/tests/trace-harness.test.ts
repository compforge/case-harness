import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  assemble,
  diagnose,
  genAiSpecs,
  normalizeJaegerSpans,
  renderInteractive,
} from "../src";

function fixtureDocuments(): Array<Record<string, unknown>> {
  const path = resolve(import.meta.dir, "../../../python/trace_harness/tests/fixtures/trace_genai_sample.jsonl");
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

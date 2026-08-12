import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  Engine,
  rampHold,
  serializeOutcomes,
  serializeRun,
  writeRunData,
  type Outcome,
  type Workload,
} from "../src";

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));
const PERF_FIXTURES = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../conformance/perf/fixtures",
);

describe("TypeScript perf harness", () => {
  test("closed-loop holds the requested concurrency and records request metrics", async () => {
    let inflight = 0;
    let peak = 0;
    const workload: Workload = {
      fire: async (): Promise<Outcome> => {
        const started = performance.now();
        inflight += 1;
        peak = Math.max(peak, inflight);
        await sleep(15);
        inflight -= 1;
        return {
          status: 200,
          duration_ms: performance.now() - started,
          metrics: { ttft_ms: 5 },
          meta: { trace_id: `trace-${Math.random()}` },
        };
      },
    };
    const run = await new Engine({
      name: "closed",
      subject: { name: "chat", target: {} },
      workload,
      loads: [rampHold("closed", 5, 0, 0.12, { graceful_stop_s: 1 })],
    }).run();

    expect(peak).toBe(5);
    expect(run.trials).toHaveLength(1);
    expect(run.trials[0]!.windows[0]!.request!.n).toBeGreaterThan(5);
    expect(run.trials[0]!.windows[0]!.request!.metrics.ttft_ms!.p95).toBe(5);
    expect(run.trials[0]!.outcomes.every(({ outcome }) => outcome.meta?.trace_id)).toBe(true);
  });

  test("request limit is an exact safety rail", async () => {
    const workload: Workload = {
      fire: async () => ({ status: 200, duration_ms: 1 }),
    };
    const run = await new Engine({
      subject: { name: "chat", target: {} },
      workload,
      loads: [rampHold("closed", 5, 0, 1, { max_requests: 12 })],
    }).run();
    expect(run.trials[0]!.stop.reason).toBe("request_limit");
    expect(run.trials[0]!.outcomes).toHaveLength(12);
  });

  test("loads multiple canonical Cases and reduces each Case independently", async () => {
    const originalRandom = Math.random;
    let pick = 0;
    Math.random = () => (pick++ % 2 === 0 ? 0.1 : 0.9);
    try {
      const run = await new Engine({
        subject: { name: "chat", target: {} },
        workload: {
          fire: async ({ case: selected }) => ({
            status: 200,
            duration_ms: selected.id === "ordinary_chat" ? 10 : 20,
          }),
        },
        caseMix: [
          { case: { id: "ordinary_chat", input: { query: "hello" } }, weight: 1 },
          { case: { id: "knowledge_chat", input: { query: "docs" } }, weight: 1 },
        ],
        loads: [rampHold("closed", 1, 0, 1, { max_requests: 4 })],
      }).run();

      const byCase = run.trials[0]!.windows[0]!.by_case;
      expect(Object.keys(byCase).sort()).toEqual(["knowledge_chat", "ordinary_chat"]);
      expect(byCase.ordinary_chat!.n + byCase.knowledge_chat!.n).toBe(4);
      expect(byCase.ordinary_chat!.p50_ms).toBe(10);
      expect(byCase.knowledge_chat!.p50_ms).toBe(20);
    } finally {
      Math.random = originalRandom;
    }
  });

  test("error-rate breaker stops a failing trial", async () => {
    const workload: Workload = {
      fire: async () => ({ status: 503, duration_ms: 1 }),
    };
    const run = await new Engine({
      subject: { name: "chat", target: {} },
      workload,
      loads: [rampHold("closed", 2, 0, 1, {
        abort_on_error_rate: 0.5,
        breaker_min_n: 4,
      })],
    }).run();
    expect(run.trials[0]!.stop.reason).toBe("error_rate");
    expect(run.passed).toBe(false);
  });

  test("validates shared safety fields before starting load", () => {
    expect(() => new Engine({
      subject: { name: "chat", target: {} },
      workload: { fire: async () => ({ status: 200, duration_ms: 1 }) },
      loads: [rampHold("closed", 1, 0, 1, { max_requests: 0 })],
    })).toThrow("max_requests");
  });

  test("empty raw outcome stream contains no invalid blank record", () => {
    expect(serializeOutcomes({
      schema: 3,
      run_id: "empty",
      experiment: "perf",
      created_at: new Date(0).toISOString(),
      subject: "chat",
      passed: false,
      trials: [],
    })).toBe("");
  });

  test("persists shared schema-3 model and raw outcomes", async () => {
    const run = await new Engine({
      subject: { name: "chat", target: {} },
      workload: { fire: async () => ({ status: 200, duration_ms: 1, meta: { trace_id: "t1" } }) },
      loads: [rampHold("closed", 1, 0, 0.03, { max_requests: 1 })],
    }, { run_id: "fixed" }).run();
    const document = serializeRun(run);
    expect(document).toMatchObject({ schema: 3, run_id: "fixed", n_trials: 1 });

    const directory = mkdtempSync(join(tmpdir(), "ts-perf-"));
    try {
      writeRunData(run, directory);
      expect(JSON.parse(readFileSync(join(directory, "run.json"), "utf8"))).toMatchObject({ schema: 3 });
      expect(JSON.parse(readFileSync(join(directory, "outcomes.jsonl"), "utf8"))).toMatchObject({
        trial: run.trials[0]!.id,
        meta: { trace_id: "t1" },
      });
      expect(JSON.parse(readFileSync(join(directory, "verdict.json"), "utf8"))).toMatchObject({
        harness: "perf",
        scope: "perf",
        run_id: "fixed",
        status: "skipped",
      });
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  test("reads the language-neutral conformance fixture", () => {
    const run = JSON.parse(readFileSync(join(PERF_FIXTURES, "basic.run.json"), "utf8"));
    const outcome = JSON.parse(readFileSync(join(PERF_FIXTURES, "basic.outcomes.jsonl"), "utf8"));

    expect(run).toMatchObject({
      schema: 3,
      trials: [{
        id: "default__closed-5c",
        arm: { id: "default__closed-5c" },
        windows: [{
          request: { metrics: { first_token_ms: { p95: 6500 } } },
          by_case: { ordinary_chat: { n: 1 } },
        }],
      }],
    });
    expect(outcome).toMatchObject({
      trial: "default__closed-5c",
      metrics: { first_token_ms: 6500 },
      meta: { trace_id: "0123456789abcdef0123456789abcdef" },
    });
  });
});

import { createHash } from "node:crypto";
import { drive } from "./scheduler";
import { buildWindows } from "./reduce";
import { loadLabel, resourceLabel, validateLoadProfile, type LoadProfile } from "./load";
import type { Arm, Case, ResourceProfile, Run, Subject, TrialRecord } from "./model";
import type { TrialContext, Workload } from "./workload";

export interface Experiment {
  name?: string;
  subject: Subject;
  workload: Workload;
  resources?: ResourceProfile[];
  loads: LoadProfile[];
  cases?: Case[];
  weights?: Record<string, number>;
  signal?: AbortSignal;
  onTrialStart?(context: TrialContext, startedAt: Date): Promise<void> | void;
  onTrialFinish?(trial: TrialRecord): Promise<void> | void;
}

function runId(now = new Date()): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function arms(experiment: Experiment): Arm[] {
  const resources = experiment.resources?.length ? experiment.resources : [{}];
  const expanded = resources.flatMap((resource) => experiment.loads.map((load) => ({
    base: `${resourceLabel(resource)}|${loadLabel(load)}`,
    resources: resource,
    load,
  })));
  const counts = new Map<string, number>();
  for (const item of expanded) counts.set(item.base, (counts.get(item.base) ?? 0) + 1);
  return expanded.map((item) => {
    const suffix = counts.get(item.base)! > 1
      ? `@${createHash("sha256").update(JSON.stringify(item)).digest("hex").slice(0, 8)}`
      : "";
    return { id: `${item.base}${suffix}`, resources: item.resources, load: item.load };
  });
}

export class Engine {
  readonly #experiment: Experiment;
  readonly #runId: string;

  constructor(experiment: Experiment, options: { run_id?: string } = {}) {
    if (!experiment.loads.length) throw new Error("perf experiment requires at least one load profile");
    experiment.loads.forEach(validateLoadProfile);
    this.#experiment = experiment;
    this.#runId = options.run_id ?? runId();
  }

  async run(): Promise<Run> {
    const created = new Date();
    const trials: TrialRecord[] = [];
    const cases = this.#experiment.cases?.length
      ? this.#experiment.cases
      : [{ id: "default", input: {} }];
    const weights = cases.map((item) => Math.max(0, this.#experiment.weights?.[item.id] ?? 1));
    for (const arm of arms(this.#experiment)) {
      if (this.#experiment.signal?.aborted) break;
      const started = new Date();
      const controller = new AbortController();
      const abort = () => controller.abort(this.#experiment.signal?.reason);
      this.#experiment.signal?.addEventListener("abort", abort, { once: true });
      const context: TrialContext = {
        subject: this.#experiment.subject,
        arm,
        run_id: this.#runId,
        signal: controller.signal,
      };
      let primaryError: unknown;
      try {
        await this.#experiment.workload.setup?.(context);
        await this.#experiment.onTrialStart?.(context, started);
        const driven = await drive({
          workload: this.#experiment.workload,
          context: { subject: context.subject, run_id: context.run_id },
          arm,
          cases,
          weights,
          signal: this.#experiment.signal,
        });
        await this.#experiment.workload.deactivate?.(context);
        const finished = new Date();
        const trial: TrialRecord = {
          id: arm.id,
          subject: this.#experiment.subject.name,
          arm,
          started_at: started.toISOString(),
          finished_at: finished.toISOString(),
          windows: buildWindows(arm.load, driven.outcomes, driven.stop.snapshot?.at_s ?? driven.elapsed_s),
          stop: driven.stop,
          outcomes: driven.outcomes,
        };
        trials.push(trial);
        await this.#experiment.onTrialFinish?.(trial);
      } catch (error) {
        primaryError = error;
        throw error;
      } finally {
        this.#experiment.signal?.removeEventListener("abort", abort);
        try {
          await this.#experiment.workload.cleanup?.(context);
        } catch (cleanupError) {
          if (!primaryError) throw cleanupError;
        }
      }
    }
    return {
      schema: 3,
      run_id: this.#runId,
      experiment: this.#experiment.name ?? "perf",
      created_at: created.toISOString(),
      subject: this.#experiment.subject.name,
      passed: trials.length === arms(this.#experiment).length
        && trials.every((trial) => trial.stop.reason === "deadline" || trial.stop.reason === "request_limit"),
      trials,
    };
  }
}

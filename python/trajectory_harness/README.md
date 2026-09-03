# trajectory_harness

Normalize agent and workflow recordings, derive measurements, discover patterns, verify
criteria, aggregate dataset-level metrics, and render comparable trajectory reports.

`Trajectory` is the normalized execution fact. `Measurements` is deterministic data derived
from that trajectory. Together they are the inputs to `Detector` (discovery and data mining)
and `Verifier` (checking an explicit criterion). Both component types declare two independent
dimensions: `category="cost" | "effect"` and `rule_type="hard" | "soft"`.

```python
from datetime import datetime, timezone

from trajectory_harness import (
    ContextUsageMeasurer,
    ExecutionSuccessVerifier,
    ModelUsageMeasurer,
    OTelJsonLoader,
    PostCompactRefetchDetector,
    RepeatedToolCallDetector,
    RetryLoopDetector,
    ToolUsageMeasurer,
    TrajectoryAnalysisRun,
    aggregate_metrics,
    detect,
    verify,
    measure,
    write_report_html,
)

detectors = (
    RepeatedToolCallDetector(),
    RetryLoopDetector(),
    PostCompactRefetchDetector(),
)
verifiers = (ExecutionSuccessVerifier(),)
measurers = (ModelUsageMeasurer(), ToolUsageMeasurer(), ContextUsageMeasurer())
trajectories = OTelJsonLoader().load("trace.json")
measurement_cells = tuple(measure(item, measurers) for item in trajectories)
measurement_inputs = tuple(cell.results for cell in measurement_cells)
run = TrajectoryAnalysisRun(
    run_id="analysis-001",
    created_at=datetime.now(timezone.utc),
    dataset_id="reviews",
    dataset_version="2026-W34",
    trajectory_ids=tuple(item.trajectory_id for item in trajectories),
    trajectory_targets=tuple((item.trajectory_id, "") for item in trajectories),
    detections=tuple(
        detect(item, detectors, measurements=derived)
        for item, derived in zip(trajectories, measurement_inputs)
    ),
    detector_specs=tuple(detector.spec for detector in detectors),
    verifications=tuple(
        verify(item, verifiers, measurements=derived)
        for item, derived in zip(trajectories, measurement_inputs)
    ),
    verifier_specs=tuple(verifier.spec for verifier in verifiers),
    measurements=measurement_cells,
    measurer_specs=tuple(measurer.spec for measurer in measurers),
)

print([metric.to_dict() for metric in aggregate_metrics(run)])
write_report_html("trajectory-report.html", [run])
```

For a repeatable source-to-report workflow, provide three focused components and compose them
with the one-click facade:

```python
from trajectory_harness import (
    TrajectoryDataset,
    TrajectoryDatasetBuilder,
    TrajectoryAnalysisRunner,
    TrajectoryHarness,
    TrajectoryReportBuilder,
)


class ReviewDatasetBuilder(TrajectoryDatasetBuilder):
    def assemble(self, recordings, trajectories, query):
        return TrajectoryDataset(
            dataset_id="reviews",
            version="2026-W34",
            trajectories=tuple(trajectories),
            annotations=join_review_labels(recordings, trajectories),
        )


class ReviewRunner(TrajectoryAnalysisRunner):
    def target_for(self, trajectory, dataset):
        return trajectory.metadata["review_stage"]


class ReviewReport(TrajectoryReportBuilder):
    report_title = "Weekly review trajectories"


harness = TrajectoryHarness(
    builder=ReviewDatasetBuilder(source=review_source, loader=review_loader),
    runner=ReviewRunner(
        detectors=review_detectors,
        verifiers=review_verifiers,
        measurers=review_measurers,
    ),
    reporter=ReviewReport(),
)
result = harness.run("runs", scope="reviews", run_id="2026-W34")

# Prior run directories are read only while rendering trends.
harness.run(
    "runs",
    scope="reviews",
    run_id="2026-W35",
    history_dirs=["runs/reviews/2026-W34"],
)

# Rebuild report.html from dataset.json + run.json without source or plugins.
ReviewReport().rerender(result.run_dir)
```

`TrajectoryDatasetBuilder` owns selection/fetch/load isolation and lets the domain assemble
labels into `TrajectoryAnnotation.annotation`. `TrajectoryAnalysisRunner` owns detector,
verifier, measurer, and metric execution over that fixed dataset. `TrajectoryReportBuilder` owns the
canonical report and accepts domain `Section` values. Source-specific queries, labels, and
business concepts remain in those domain components; `TrajectoryHarness` only composes them.

The processing boundary is:

```text
Source
  -> RecordingRef / Recording
  -> TrajectoryLoader
  -> TrajectoryDataset (trajectories + annotations)
  -> Measurements (deterministically derived from Trajectory)
  -> Trajectory + Measurements
       -> Detector -> DetectionResult (findings)
       -> Verifier -> VerificationResult (verdict and/or score)
  -> TrajectoryAnalysisRun (Worksheet results + target/category dimensions)
  -> Metric
  -> Report / HTML
```

Source implementations discover lightweight `RecordingRef` values and fetch raw `Recording`
text. Loaders own format parsing and can consume either files with `load` or fetched content with
`loads`; dataset builders attach labels separately instead of coupling annotations to storage.

The bundled loader accepts OTLP JSON, Tempo's OTLP wrapper, and flat OTLP JSONL. Message
payloads follow the OTel GenAI `role + parts` schema. A failed operation carries a
normalized `Failure(kind, phase, error_type)`; for example `llm.request.timeout` or
`tool.prepare.dependency_missing`.

A trajectory may contain one agent loop or a pipeline of several agent loops and deterministic
operations. `Step.parent_step_id` preserves that execution hierarchy; domain verifiers select
the relevant subtrees through step `operation`, `name`, and `attributes`. The common model does
not introduce a separate stage abstraction. `Trajectory.generation` is a provenance map for the
agent, instruction/skill, tool-contract, model, loop, and orchestration versions that actually
produced the behavior. Loaders and project wrappers populate it; it is not a separate domain object
and is never inferred from Dataset or Verifier versions.

Recurring LLM failures use the shared `llm_failure(phase, error_type)` constructor;
`llm_timeout(phase)` narrows timeouts to observed boundaries such as `connect`,
`first_chunk`, or `inter_chunk`. Use `request` when a non-streaming source exposes only
an overall deadline. Common error types include `timeout`, `rate_limit`, `client_error`,
`server_error`, `network_error`, `invalid_response`, and `unknown`. Loaders still own
source-specific parsing and may use open strings for domain-specific tool, agent, and
workflow failures.

Common detectors and verifiers ship with the Harness. Detectors discover patterns and produce
Findings without a verdict; Verifiers check explicit criteria and produce a verdict and/or score.
Either may analyze cost or effect, and either may be implemented as a hard deterministic rule or
a soft model-based rule. Measurers are the implementation mechanism that derives factual
per-trajectory Measurements before Detector and Verifier execution. `aggregate_metrics` turns
execution facts, failures, detections, verifications, and
measurements into dataset-level metrics. It does
not manufacture a weighted overall score.

`ModelUsageMeasurer` reports model-call count, usage coverage, input/output/cache tokens, and
per-call input-token average and peak. `ToolUsageMeasurer` reports executed calls, failures,
duration, result bytes and coverage, and observed concurrency. `ContextUsageMeasurer` reports
input-token growth and compact-boundary deltas. Higher usage may be necessary for a harder task or
may be waste; the Harness does not judge that without an effect contract. Dataset aggregations
retain both totals and normalized `mean`/`p50`/`p95` values.
Optimization patterns are findings, not execution failures, verifier verdicts, or raw
measurements. For example, exact repeated tool calls produce a `Finding`. The finding records an interpreted
problem pattern and evidence separately from hypotheses such as missing batching, unclear tool
guidance, or an ineffective repeat-call stopping strategy. Retry loops and exact post-compact
refetches are also common Findings; whether a retry or refresh was necessary remains a domain or
experiment question.
Detector findings and Verifier verdicts remain separate from runtime `Failure`: a domain rule may return
`verdict="fail"`, while `status="error"` is reserved for a verifier that could not run.

The common detector catalog grows around reusable findings from the three parts of an agent
loop: system prompt behavior, tool-set use, and loop mechanisms such as context and stopping.
This mapping is diagnostic rather than causal: one finding may point to several design surfaces,
while business-specific contracts and cross-loop pipeline judgments remain domain verifiers.
The HTML report keeps low-cardinality failure metrics and lists the affected trajectory IDs,
so consumers can correlate failures with case attributes without turning case IDs into metric
dimensions.

`trajectory_harness` owns the trajectory-specific report sections and HTML entry point.
Report functions can aggregate full runs or accept persisted `Metric` values for historical
trends. Trend time comes from `TrajectoryAnalysisRun.created_at`; `run_id` is only an opaque identity,
so callers may schedule runs weekly, per release, or on demand. The final low-level document
rendering remains in `harness_common.report_kit`, so consumers can append business-specific
`Section` values without writing HTML. A domain may pass `ParetoSpec` with explicit effect and cost
Metric selectors; the report then shows completion, duration p95, and dominated runs without
guessing which quality metric represents effect.

The facade writes `dataset.json`, one current `run.json`, `report.html`, and `verdict.json` under
`runs/<scope>/<run-id>/`. The dataset artifact contains trajectories, labels, and build health;
the run artifact contains detector findings, verifier judgments, measurement evidence, metrics,
and references to trajectory IDs. Historical runs are report inputs rather than copies inside the current run,
avoiding quadratic storage. Without a domain verdict policy, successful analysis is `skipped`
rather than silently treating findings as gates.

See [`../../docs/trajectory-harness.md`](../../docs/trajectory-harness.md) for the model and
its boundary with eval/trace analysis.

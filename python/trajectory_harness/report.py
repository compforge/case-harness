"""Trajectory-domain report projection and HTML facade."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from harness_common.report_kit import (
    Chart,
    Heading,
    KV,
    LineSeries,
    Report,
    Section,
    Table,
    render_html,
)
from trajectory_harness.build import DatasetBuildSummary
from trajectory_harness.metrics import (
    Metric,
    TrajectoryEvaluationRun,
    aggregate_metrics,
)
from trajectory_harness.runio import TrajectoryRunArtifact, load_run_artifact

REPORT_FILE = "report.html"


@dataclass(frozen=True, slots=True)
class _RunView:
    """Presentation view over one persisted Worksheet run."""

    run: TrajectoryEvaluationRun

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def created_at(self):
        return self.run.created_at

    @property
    def dataset_id(self) -> str:
        return self.run.dataset_id

    @property
    def dataset_version(self) -> str:
        return self.run.dataset_version

    @property
    def label(self) -> str:
        return self.run.dataset_id

    @property
    def evaluations(self):
        return self.run.evaluations

    @property
    def measurements(self):
        return self.run.measurements

    @property
    def evaluator_specs(self):
        return self.run.evaluator_specs

    @property
    def measurer_specs(self):
        return self.run.measurer_specs


class TrajectoryReportBuilder:
    """Pure run-artifact-to-report stage; domains may add presentation sections."""

    report_title = "Trajectory evaluation"

    def extra_sections(
        self,
        current: TrajectoryRunArtifact,
        history: Sequence[TrajectoryRunArtifact],
    ) -> Iterable[Section]:
        return ()

    def build(
        self,
        current: TrajectoryRunArtifact,
        *,
        history: Sequence[TrajectoryRunArtifact] = (),
    ) -> Report:
        artifacts = (*history, current)
        runs = tuple(artifact.run for artifact in artifacts)
        sections = [_collection_section(current.build.summary)]
        sections.extend(self.extra_sections(current, history))
        return build_report(
            runs,
            title=self.report_title,
            extra_sections=sections,
        )

    def write(
        self,
        run_dir: str | Path,
        current: TrajectoryRunArtifact,
        *,
        history: Sequence[TrajectoryRunArtifact] = (),
    ) -> Path:
        target = Path(run_dir) / REPORT_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_html(self.build(current, history=history)), encoding="utf-8"
        )
        return target

    def rerender(
        self,
        run_dir: str | Path,
        *,
        history_dirs: Sequence[str | Path] = (),
    ) -> Path:
        """Re-render solely from persisted artifacts, without collection/evaluation."""

        current = load_run_artifact(run_dir)
        history = tuple(load_run_artifact(path) for path in history_dirs)
        return self.write(run_dir, current, history=history)


def _collection_section(summary: DatasetBuildSummary) -> Section:
    query = summary.query
    blocks = [
        KV(
            items=[
                ("Selected recordings", str(summary.selected_recordings)),
                ("Fetched recordings", str(summary.fetched_recordings)),
                ("Loaded trajectories", str(summary.loaded_trajectories)),
                ("Included trajectories", str(summary.included_trajectories)),
                ("Dataset annotations", str(summary.included_annotations)),
                (
                    "Annotations without trajectory",
                    str(summary.unmatched_annotations),
                ),
                ("Dataset issues", str(len(summary.issues))),
                (
                    "Started at or after",
                    str(query.get("started_at_or_after") or "—"),
                ),
                ("Started before", str(query.get("started_before") or "—")),
                ("Limit", str(query.get("limit") or "—")),
                (
                    "Query attributes",
                    json.dumps(
                        query.get("attributes") or {},
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
    ]
    if summary.issues:
        blocks.append(
            Table(
                columns=["Recording", "Phase", "URI", "Error"],
                rows=[
                    [item.recording_id, item.phase, item.uri, item.error]
                    for item in summary.issues
                ],
            )
        )
    return Section(heading="Dataset build health", blocks=blocks)


def build_report(
    runs: Sequence[TrajectoryEvaluationRun],
    *,
    title: str = "Trajectory evaluation",
    metrics: Sequence[Metric] | None = None,
    extra_sections: Iterable[Section] = (),
) -> Report:
    """Build the canonical trajectory report from one or more evaluation runs."""

    ordered = sorted(runs, key=lambda run: (run.created_at, run.run_id))
    views = tuple(_RunView(run) for run in ordered)
    run_metrics = _run_metrics(views, metrics)
    latest_by_dataset = {}
    for pair in run_metrics:
        latest_by_dataset[pair[0].label] = pair
    latest_runs = tuple(pair[0] for pair in latest_by_dataset.values())
    latest = ordered[-1] if ordered else None
    sections = [
        _runs_section(views),
        _execution_section(tuple(latest_by_dataset.values())),
        _evaluators_section(views),
        _measurers_section(views),
        _metrics_section(tuple(latest_by_dataset.values())),
        _evaluation_evidence_section(latest_runs),
        _measurement_evidence_section(latest_runs),
        _trends_section(run_metrics),
    ]
    sections.extend(extra_sections)
    meta = [("Runs", str(len(ordered)))]
    if latest:
        meta.extend(
            (
                ("Latest run", latest.run_id),
                ("Datasets", ", ".join(sorted({run.dataset_id for run in ordered}))),
            )
        )
    return Report(title=title, meta=meta, sections=sections)


def render_report_html(
    runs: Sequence[TrajectoryEvaluationRun],
    *,
    title: str = "Trajectory evaluation",
    metrics: Sequence[Metric] | None = None,
    extra_sections: Iterable[Section] = (),
) -> str:
    """Render trajectory evaluation runs as a standalone HTML document."""

    return render_html(
        build_report(
            runs,
            title=title,
            metrics=metrics,
            extra_sections=extra_sections,
        )
    )


def write_report_html(
    path: str | Path,
    runs: Sequence[TrajectoryEvaluationRun],
    *,
    title: str = "Trajectory evaluation",
    metrics: Sequence[Metric] | None = None,
    extra_sections: Iterable[Section] = (),
) -> Path:
    """Write the canonical HTML report and return its path."""

    target = Path(path)
    target.write_text(
        render_report_html(
            runs,
            title=title,
            metrics=metrics,
            extra_sections=extra_sections,
        ),
        encoding="utf-8",
    )
    return target


def _run_metrics(
    runs: Sequence[_RunView], metrics: Sequence[Metric] | None
) -> list[tuple[_RunView, tuple[Metric, ...]]]:
    if metrics is None:
        return [
            (
                run,
                run.run.metrics or aggregate_metrics(run.run),
            )
            for run in runs
        ]
    grouped = defaultdict(list)
    for metric in metrics:
        grouped[
            (
                metric.run_id,
                metric.dataset_id,
                metric.dataset_version,
            )
        ].append(metric)
    return [
        (
            run,
            tuple(
                grouped[
                    (
                        run.run_id,
                        run.dataset_id,
                        run.dataset_version,
                    )
                ]
            ),
        )
        for run in runs
    ]


def _runs_section(runs: Sequence[_RunView]) -> Section:
    return Section(
        heading="Evaluation runs and datasets",
        blocks=[
            Table(
                columns=[
                    "Run",
                    "Created at",
                    "Dataset",
                    "Version",
                    "Evaluation cells",
                    "Measurement cells",
                    "Annotations",
                ],
                rows=[
                    [
                        run.run_id,
                        run.created_at.isoformat(),
                        run.label,
                        run.dataset_version or "—",
                        str(len(run.evaluations)),
                        str(len(run.measurements)),
                        (
                            str(run.run.annotation_count)
                            if run.run.annotation_count is not None
                            else "—"
                        ),
                    ]
                    for run in runs
                ],
            )
        ],
    )


def _execution_section(
    latest: Sequence[tuple[_RunView, tuple[Metric, ...]]],
) -> Section:
    if not latest:
        return Section(heading="Execution and failures", blocks=[])

    blocks = []
    for run, metrics in sorted(latest, key=lambda pair: pair[0].label):
        summary_names = {
            "trajectory",
            "execution.completion",
            "execution.timeout",
            "execution.failure",
            "execution.duration_ms",
        }
        summary = [metric for metric in metrics if metric.name in summary_names]
        failures = [
            metric
            for metric in metrics
            if metric.name == "failure" and metric.aggregation == "count"
        ]
        blocks.extend(
            (
                Heading(run.label),
                KV(
                    items=[
                        (_metric_label(metric), _metric_value(metric))
                        for metric in summary
                    ]
                ),
            )
        )
        if failures:
            blocks.append(
                Table(
                    columns=["Impact", "Kind", "Phase", "Error type", "Count"],
                    rows=[
                        [
                            _dimension(metric, "impact"),
                            _dimension(metric, "kind"),
                            _dimension(metric, "phase"),
                            _dimension(metric, "error_type"),
                            _metric_value(metric),
                        ]
                        for metric in failures
                    ],
                    sort_default=(4, "desc"),
                )
            )
        affected = _failure_rows(run)
        if affected:
            blocks.append(
                Table(
                    columns=[
                        "Trajectory",
                        "Target",
                        "Impact",
                        "Failure",
                        "Code",
                        "Message",
                    ],
                    rows=affected,
                )
            )
    return Section(heading="Execution and failures", blocks=blocks)


def _failure_rows(run: _RunView) -> list[list[str]]:
    rows = []
    trajectories = {
        item.trajectory.trajectory_id: item.trajectory
        for item in (*run.evaluations, *run.measurements)
    }
    for trajectory in trajectories.values():
        for step in trajectory.steps:
            if step.failure:
                rows.append(
                    [
                        trajectory.trajectory_id,
                        run.run.target_for(trajectory.trajectory_id) or "—",
                        f"step:{step.step_id}",
                        step.failure.key,
                        step.failure.code or "—",
                        step.failure.message or "—",
                    ]
                )
        if trajectory.execution and trajectory.execution.failure:
            failure = trajectory.execution.failure
            rows.append(
                [
                    trajectory.trajectory_id,
                    run.run.target_for(trajectory.trajectory_id) or "—",
                    "execution",
                    failure.key,
                    failure.code or "—",
                    failure.message or "—",
                ]
            )
    return rows


def _evaluators_section(runs: Sequence[_RunView]) -> Section:
    specs = {}
    for run in runs:
        for spec in run.evaluator_specs:
            specs[spec.evaluator_id] = spec
    return Section(
        heading="Evaluator catalog",
        blocks=[
            Table(
                columns=["Evaluator", "Category", "Kind", "Owner", "Description"],
                rows=[
                    [
                        spec.evaluator_id,
                        spec.category,
                        spec.kind,
                        spec.owner or "—",
                        spec.description,
                    ]
                    for spec in sorted(
                        specs.values(), key=lambda item: item.evaluator_id
                    )
                ],
            )
        ],
    )


def _measurers_section(runs: Sequence[_RunView]) -> Section:
    specs = {}
    for run in runs:
        for spec in run.measurer_specs:
            specs[spec.measurer_id] = spec
    return Section(
        heading="Measurer catalog",
        blocks=[
            Table(
                columns=[
                    "Measurer",
                    "Category",
                    "Owner",
                    "Measurements",
                    "Description",
                ],
                rows=[
                    [
                        spec.measurer_id,
                        spec.category,
                        spec.owner or "—",
                        ", ".join(item.name for item in spec.measurements) or "—",
                        spec.description,
                    ]
                    for spec in sorted(
                        specs.values(), key=lambda item: item.measurer_id
                    )
                ],
            )
        ],
    )


def _metrics_section(
    latest: Sequence[tuple[_RunView, tuple[Metric, ...]]],
) -> Section:
    return Section(
        heading="Latest metrics",
        blocks=[
            Table(
                columns=["Dataset", "Metric", "Value", "Unit", "Direction"],
                rows=[
                    [
                        run.label,
                        _metric_label(metric),
                        _format_number(metric.value),
                        metric.unit or "—",
                        metric.direction,
                    ]
                    for run, metrics in latest
                    for metric in metrics
                ],
            )
        ]
        if latest
        else [],
    )


def _evaluation_evidence_section(runs: Sequence[_RunView]) -> Section:
    rows = []
    for run in sorted(runs, key=lambda item: item.label):
        for item in run.evaluations:
            for result in item.results:
                findings = result.findings or (None,)
                for finding in findings:
                    rows.append(
                        [
                            run.label,
                            item.trajectory.trajectory_id,
                            item.target or "—",
                            item.category,
                            result.evaluator_id,
                            result.status,
                            result.verdict or "—",
                            (
                                _format_number(result.score)
                                if result.score is not None
                                else "—"
                            ),
                            finding.code if finding else "—",
                            finding.severity if finding else "—",
                            finding.summary if finding else "—",
                            ", ".join(finding.step_ids if finding else result.step_ids)
                            or "—",
                            "; ".join(finding.hypotheses) if finding else "—",
                            result.explanation or "—",
                        ]
                    )
    return Section(
        heading="Evaluation evidence",
        blocks=[
            Table(
                columns=[
                    "Dataset",
                    "Trajectory",
                    "Target",
                    "Category",
                    "Evaluator",
                    "Status",
                    "Verdict",
                    "Score",
                    "Finding",
                    "Severity",
                    "Summary",
                    "Steps",
                    "Hypotheses",
                    "Explanation",
                ],
                rows=rows,
            )
        ]
        if rows
        else [],
    )


def _measurement_evidence_section(runs: Sequence[_RunView]) -> Section:
    rows = []
    for run in sorted(runs, key=lambda item: item.label):
        for item in run.measurements:
            for result in item.results:
                measurements = result.measurements.items() or (("—", "—"),)
                for name, value in measurements:
                    rows.append(
                        [
                            run.label,
                            item.trajectory.trajectory_id,
                            item.target or "—",
                            item.category,
                            result.measurer_id,
                            result.status,
                            str(name),
                            _measurement_value(value),
                            ", ".join(result.step_ids) or "—",
                            result.explanation or "—",
                        ]
                    )
    return Section(
        heading="Measurement evidence",
        blocks=[
            Table(
                columns=[
                    "Dataset",
                    "Trajectory",
                    "Target",
                    "Category",
                    "Measurer",
                    "Status",
                    "Measurement",
                    "Value",
                    "Steps",
                    "Explanation",
                ],
                rows=rows,
            )
        ]
        if rows
        else [],
    )


def _trends_section(
    run_metrics: Sequence[tuple[_RunView, tuple[Metric, ...]]],
) -> Section:
    if len({(run.run_id, run.created_at) for run, _ in run_metrics}) < 2:
        return Section(heading="Metric trends", blocks=[])

    grouped: dict[tuple, list[Metric]] = defaultdict(list)
    created_at = {}
    for run, metrics in run_metrics:
        created_at[
            (
                run.run_id,
                run.dataset_id,
                run.dataset_version,
            )
        ] = run.created_at.isoformat()
        for metric in metrics:
            identity = (
                metric.name,
                metric.unit,
                metric.aggregation,
                metric.dimensions,
            )
            grouped[identity].append(metric)

    blocks = []
    for identity, metrics in sorted(grouped.items(), key=lambda item: str(item[0])):
        by_dataset: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for metric in metrics:
            dataset = metric.dataset_id
            timestamp = created_at[
                (
                    metric.run_id,
                    metric.dataset_id,
                    metric.dataset_version,
                )
            ]
            by_dataset[dataset].append((timestamp, metric.value))
        if max((len(points) for points in by_dataset.values()), default=0) < 2:
            continue
        exemplar = metrics[0]
        blocks.append(
            Chart(
                title=_metric_label(exemplar),
                series=[
                    LineSeries(name=dataset, points=points)
                    for dataset, points in sorted(by_dataset.items())
                ],
                x_label="time",
                x_kind="time",
                y_label=exemplar.unit,
            )
        )
    return Section(heading="Metric trends", blocks=blocks)


def _metric_label(metric: Metric) -> str:
    return metric.qualified_name


def _metric_value(metric: Metric) -> str:
    value = _format_number(metric.value)
    return f"{value} {metric.unit}" if metric.unit else value


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _measurement_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return _format_number(float(value))
    return str(value)


def _dimension(metric: Metric, name: str) -> str:
    return dict(metric.dimensions).get(name, "")

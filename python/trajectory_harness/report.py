"""Trajectory-domain report projection and HTML facade."""

from __future__ import annotations

from collections import defaultdict
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
from trajectory_harness.metrics import EvaluationRun, Metric, aggregate_metrics


def build_report(
    runs: Sequence[EvaluationRun],
    *,
    title: str = "Trajectory evaluation",
    metrics: Sequence[Metric] | None = None,
    extra_sections: Iterable[Section] = (),
) -> Report:
    """Build the canonical trajectory report from one or more evaluation runs."""

    ordered = sorted(runs, key=lambda run: (run.created_at, run.run_id))
    run_metrics = _run_metrics(ordered, metrics)
    latest_by_dataset = {}
    for pair in run_metrics:
        latest_by_dataset[pair[0].dataset.label] = pair
    latest = ordered[-1] if ordered else None
    sections = [
        _runs_section(ordered),
        _execution_section(tuple(latest_by_dataset.values())),
        _evaluators_section(ordered),
        _metrics_section(tuple(latest_by_dataset.values())),
        _trends_section(run_metrics),
    ]
    sections.extend(extra_sections)
    meta = [("Runs", str(len(ordered)))]
    if latest:
        meta.extend(
            (
                ("Latest run", latest.run_id),
                ("Datasets", ", ".join(sorted({run.dataset.label for run in ordered}))),
            )
        )
    return Report(title=title, meta=meta, sections=sections)


def render_report_html(
    runs: Sequence[EvaluationRun],
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
    runs: Sequence[EvaluationRun],
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
    runs: Sequence[EvaluationRun], metrics: Sequence[Metric] | None
) -> list[tuple[EvaluationRun, tuple[Metric, ...]]]:
    if metrics is None:
        return [(run, aggregate_metrics(run)) for run in runs]
    grouped = defaultdict(list)
    for metric in metrics:
        grouped[(metric.run_id, metric.dataset_id, metric.dataset_slice)].append(metric)
    return [
        (
            run,
            tuple(grouped[(run.run_id, run.dataset.dataset_id, run.dataset.slice)]),
        )
        for run in runs
    ]


def _runs_section(runs: Sequence[EvaluationRun]) -> Section:
    return Section(
        heading="Evaluation runs and datasets",
        blocks=[
            Table(
                columns=[
                    "Run",
                    "Created at",
                    "Dataset",
                    "Version",
                    "Items",
                    "Declared samples",
                ],
                rows=[
                    [
                        run.run_id,
                        run.created_at.isoformat(),
                        run.dataset.label,
                        run.dataset.version or "—",
                        str(len(run.items)),
                        (
                            str(run.dataset.sample_count)
                            if run.dataset.sample_count is not None
                            else "—"
                        ),
                    ]
                    for run in runs
                ],
            )
        ],
    )


def _execution_section(
    latest: Sequence[tuple[EvaluationRun, tuple[Metric, ...]]],
) -> Section:
    if not latest:
        return Section(heading="Execution and failures", blocks=[])

    blocks = []
    for run, metrics in sorted(latest, key=lambda pair: pair[0].dataset.label):
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
                Heading(run.dataset.label),
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
    return Section(heading="Execution and failures", blocks=blocks)


def _evaluators_section(runs: Sequence[EvaluationRun]) -> Section:
    specs = {}
    for run in runs:
        for spec in run.evaluator_specs:
            specs[spec.evaluator_id] = spec
    return Section(
        heading="Evaluator catalog",
        blocks=[
            Table(
                columns=["Evaluator", "Kind", "Owner", "Measurements", "Description"],
                rows=[
                    [
                        spec.evaluator_id,
                        spec.kind,
                        spec.owner or "—",
                        ", ".join(item.name for item in spec.measurements) or "—",
                        spec.description,
                    ]
                    for spec in sorted(
                        specs.values(), key=lambda item: item.evaluator_id
                    )
                ],
            )
        ],
    )


def _metrics_section(
    latest: Sequence[tuple[EvaluationRun, tuple[Metric, ...]]],
) -> Section:
    return Section(
        heading="Latest metrics",
        blocks=[
            Table(
                columns=["Dataset", "Metric", "Value", "Unit", "Direction"],
                rows=[
                    [
                        run.dataset.label,
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


def _trends_section(
    run_metrics: Sequence[tuple[EvaluationRun, tuple[Metric, ...]]],
) -> Section:
    if len(run_metrics) < 2:
        return Section(heading="Metric trends", blocks=[])

    grouped: dict[tuple, list[Metric]] = defaultdict(list)
    created_at = {}
    for run, metrics in run_metrics:
        created_at[(run.run_id, run.dataset.dataset_id, run.dataset.slice)] = (
            run.created_at.isoformat()
        )
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
            dataset = (
                f"{metric.dataset_id}/{metric.dataset_slice}"
                if metric.dataset_slice
                else metric.dataset_id
            )
            timestamp = created_at[
                (metric.run_id, metric.dataset_id, metric.dataset_slice)
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


def _dimension(metric: Metric, name: str) -> str:
    return dict(metric.dimensions).get(name, "")

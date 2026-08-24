from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from harness_common.report_kit import Prose, Section
from harness_common.verdict import CheckVerdict
from trajectory_harness import (
    ExecutionResult,
    ModelUsageMeasurer,
    Recording,
    RecordingQuery,
    RecordingRef,
    RepeatedToolCallEvaluator,
    Step,
    Trajectory,
    TrajectoryDataset,
    TrajectoryDatasetBuilder,
    TrajectoryEvaluationRunner,
    TrajectoryHarness,
    TrajectoryReportBuilder,
    TrajectoryAnnotation,
    load_dataset_artifact,
    load_run_artifact,
)


class _Source:
    refs = [
        RecordingRef("ok", "memory://ok"),
        RecordingRef("bad-load", "memory://bad-load"),
        RecordingRef("bad-fetch", "memory://bad-fetch"),
    ]

    def select(self, query=None):
        del query
        return self.refs

    def fetch(self, ref):
        if ref.recording_id == "bad-fetch":
            raise OSError("source unavailable")
        return Recording(ref=ref, text=ref.recording_id)


class _HealthySource(_Source):
    refs = [RecordingRef("ok", "memory://ok")]


class _Loader:
    def load(self, source):
        return self.loads(str(source), source=str(source))

    def loads(self, text, *, source=""):
        if text == "bad-load":
            raise ValueError("unsupported recording")
        tool_call = {
            "role": "assistant",
            "parts": [{"type": "tool_call", "name": "read", "arguments": {"p": 1}}],
        }
        return [
            Trajectory(
                trajectory_id=text,
                source=source,
                metadata={"review_stage": "review1"},
                steps=(
                    Step(
                        "model",
                        None,
                        "chat",
                        "model",
                        0,
                        1,
                        attributes={
                            "gen_ai.usage.input_tokens": 12,
                            "gen_ai.usage.output_tokens": 3,
                        },
                    ),
                    Step(
                        "tool-1",
                        None,
                        "execute_tool",
                        "read",
                        1,
                        1,
                        input_messages=(tool_call,),
                    ),
                    Step(
                        "tool-2",
                        None,
                        "execute_tool",
                        "read",
                        2,
                        1,
                        input_messages=(tool_call,),
                    ),
                ),
                execution=ExecutionResult("completed", duration_ms=3),
            )
        ]


class _CCRDatasetBuilder(TrajectoryDatasetBuilder):
    def __init__(self, *, source, version):
        super().__init__(source=source, loader=_Loader())
        self.version = version

    def assemble(self, recordings, trajectories, query):
        del query
        by_recording = {
            recording.recording_id: tuple(
                item.trajectory_id
                for item in trajectories
                if item.recording_id == recording.recording_id
            )
            for recording in recordings
        }
        annotations = tuple(
            TrajectoryAnnotation(
                annotation_id=f"annotation-{recording.recording_id}",
                recording_id=recording.recording_id,
                trajectory_ids=by_recording.get(recording.recording_id, ()),
                annotation={"label": "correct"},
                dimensions={"lane": "review1"},
            )
            for recording in recordings
        )
        return TrajectoryDataset(
            dataset_id="ccr-reviews",
            version=self.version,
            trajectories=tuple(trajectories),
            annotations=annotations,
            metadata={"domain": "ccr"},
        )


class _CCRRunner(TrajectoryEvaluationRunner):
    def target_for(self, trajectory, dataset):
        del dataset
        return trajectory.metadata["review_stage"]

    def metadata_for(self, dataset):
        return {"domain": dataset.metadata["domain"]}


class _CCRReport(TrajectoryReportBuilder):
    report_title = "CCR weekly report"

    def extra_sections(self, current, history):
        del history
        labels = sorted(
            str(annotation.annotation["label"])
            for annotation in current.dataset.annotations
        )
        return [Section("CCR details", [Prose(", ".join(labels))])]


def _harness(source, version, *, verdict_policy=None):
    return TrajectoryHarness(
        builder=_CCRDatasetBuilder(source=source, version=version),
        runner=_CCRRunner(
            evaluators=(RepeatedToolCallEvaluator(),),
            measurers=(ModelUsageMeasurer(),),
        ),
        reporter=_CCRReport(),
        verdict_policy=verdict_policy,
    )


class _PassingPolicy:
    def evaluate(self, artifact):
        return [
            CheckVerdict(
                name="wrong_rate <= 0.1",
                status="pass",
                metric="wrong_rate",
                observed=0.05,
            )
        ]


class _InvalidPolicy:
    def evaluate(self, artifact):
        del artifact
        return [CheckVerdict(name="invalid", status="warning")]


def test_harness_persists_current_run_and_rerenders_without_source(tmp_path):
    result = _harness(_Source(), "2026-W34").run(
        tmp_path,
        scope="ccr-weekly",
        run_id="weekly-2026-W34",
        query=RecordingQuery(
            started_at_or_after=datetime(2026, 8, 17, tzinfo=timezone.utc),
            started_before=datetime(2026, 8, 24, tzinfo=timezone.utc),
            attributes={"repository": "example/review"},
        ),
        created_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )

    assert result.run_dir == tmp_path / "ccr-weekly" / "weekly-2026-W34"
    assert result.dataset_path == result.run_dir / "dataset.json"
    assert result.run_path == result.run_dir / "run.json"
    assert result.report_path == result.run_dir / "report.html"
    assert result.verdict_path == result.run_dir / "verdict.json"
    assert result.artifact.build.summary.selected_recordings == 3
    assert result.artifact.build.summary.fetched_recordings == 2
    assert result.artifact.build.summary.loaded_trajectories == 1
    assert result.artifact.build.summary.included_annotations == 3
    assert result.artifact.build.summary.unmatched_annotations == 2
    assert result.artifact.dataset.trajectories[0].recording_id == "ok"
    dataset_doc = json.loads(result.dataset_path.read_text())
    assert "bundles" not in dataset_doc["dataset"]
    assert dataset_doc["dataset"]["trajectories"][0]["recording_id"] == "ok"
    assert [item.phase for item in result.artifact.build.summary.issues] == [
        "load",
        "fetch",
    ]
    assert result.artifact.run.annotation_count == 1
    assert result.artifact.run.trajectory_targets == (("ok", "review1"),)
    assert result.artifact.run.evaluations[0].target == "review1"
    assert result.artifact.run.evaluations[0].category == "quality"
    assert result.artifact.run.measurements[0].category == "cost"
    assert all(
        metric.dataset_version == "2026-W34" for metric in result.artifact.run.metrics
    )
    assert json.loads(result.verdict_path.read_text())["status"] == "error"

    loaded = load_run_artifact(result.run_dir)
    assert loaded == result.artifact
    assert load_dataset_artifact(result.run_dir) == result.artifact.build
    result.report_path.write_text("stale", encoding="utf-8")
    html = _CCRReport().rerender(result.run_dir).read_text(encoding="utf-8")
    assert "CCR weekly report" in html
    assert "Dataset build health" in html
    assert "unsupported recording" in html
    assert "Evaluation evidence" in html
    assert "repeated_tool_call" in html
    assert "Measurement evidence" in html
    assert "input_tokens" in html
    assert "CCR details" in html
    assert "correct" in html


def test_history_is_loaded_for_report_but_not_embedded_in_current_run(tmp_path):
    first = _harness(_HealthySource(), "2026-W34").run(
        tmp_path,
        scope="ccr-weekly",
        run_id="weekly-2026-W34",
        created_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    second = _harness(_HealthySource(), "2026-W35").run(
        tmp_path,
        scope="ccr-weekly",
        run_id="weekly-2026-W35",
        created_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        history_dirs=(first.run_dir,),
    )

    run_text = second.run_path.read_text(encoding="utf-8")
    assert "weekly-2026-W34" not in run_text
    assert "2026-W34" not in run_text
    trend_html = second.report_path.read_text(encoding="utf-8")
    assert "2026-08-24T00:00:00+00:00" in trend_html
    assert "2026-08-31T00:00:00+00:00" in trend_html
    assert '"type": "time"' in trend_html
    assert json.loads(second.verdict_path.read_text())["status"] == "skipped"


def test_runner_preserves_target_and_category_as_worksheet_dimensions():
    dataset = TrajectoryDataset(
        dataset_id="ccr-reviews",
        version="2026-W34",
        trajectories=(
            Trajectory(
                trajectory_id="review-1",
                steps=(),
                metadata={"review_stage": "review1"},
            ),
            Trajectory(
                trajectory_id="review-2",
                steps=(),
                metadata={"review_stage": "review2"},
            ),
        ),
        metadata={"domain": "ccr"},
    )

    run = _CCRRunner(
        evaluators=(RepeatedToolCallEvaluator(),),
        measurers=(ModelUsageMeasurer(),),
    ).run(dataset, run_id="compare-reviews")

    assert run.trajectory_targets == (
        ("review-1", "review1"),
        ("review-2", "review2"),
    )
    assert {(item.target, item.category) for item in run.evaluations} == {
        ("review1", "quality"),
        ("review2", "quality"),
    }
    assert {(item.target, item.category) for item in run.measurements} == {
        ("review1", "cost"),
        ("review2", "cost"),
    }
    names = {metric.qualified_name for metric in run.metrics}
    assert "trajectory.count{target=review1}" in names
    assert "trajectory.count{target=review2}" in names


def test_dataset_rejects_cross_recording_trajectory_reference():
    with pytest.raises(ValueError, match="from recording 'recording-a'"):
        TrajectoryDataset(
            dataset_id="dataset",
            version="v1",
            trajectories=(
                Trajectory(
                    trajectory_id="trajectory",
                    steps=(),
                    recording_id="recording-a",
                ),
            ),
            annotations=(
                TrajectoryAnnotation(
                    annotation_id="annotation",
                    recording_id="recording-b",
                    trajectory_ids=("trajectory",),
                ),
            ),
        )


def test_domain_policy_is_the_only_source_of_pass_verdict(tmp_path):
    result = _harness(
        _HealthySource(), "2026-W34", verdict_policy=_PassingPolicy()
    ).run(tmp_path, scope="ccr-weekly", run_id="with-policy")

    verdict = json.loads(result.verdict_path.read_text())
    assert verdict["status"] == "pass"
    assert verdict["checks"][0]["name"] == "wrong_rate <= 0.1"


def test_invalid_policy_check_becomes_error_verdict(tmp_path):
    result = _harness(
        _HealthySource(), "2026-W34", verdict_policy=_InvalidPolicy()
    ).run(tmp_path, scope="ccr-weekly", run_id="invalid-policy")

    verdict = json.loads(result.verdict_path.read_text())
    assert verdict["status"] == "error"
    assert "invalid status 'warning'" in verdict["reason"]
    assert "checks" not in verdict

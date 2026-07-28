"""Run persistence — the MODEL layer on disk, separate from the human report.

A run dir (``runs/<experiment>/<run_id>/``) holds three artifact layers:

  raw    ``outcomes.jsonl``（每请求一行的事实，含 warmup/drop）+ ``timeseries.csv``
         （probe 每 tick 采样）— append-only facts, never re-derived.
  model  ``run.json`` — the FULL serialized ``Run``（schema 版本化）: per trial the
         resources / load（含停止策略）/ stop / SLO 明细、metric registry（family →
         unit/kind/source/description）、每个请求 slice（overall/by_facet/by_stage，
         含 per_request summaries + caveats）、每条 probe series 的 typed summary。
         内存模型知道的一切，离线同样可寻址。
  views  ``report.md/html`` + ``summary/by_facet.csv``（``report.py``）— 给人看的
         渲染，从模型导出，不是事实来源。

``write_run_data`` lays down raw + model. ``load_run`` reconstructs the ``Run``
from a run dir — so ``MetricStore(load_run(d).trials)`` serves the SAME
``<family>{labels}.<stat>`` reads offline that the live process served, and SLO /
analysis can re-evaluate without re-firing. ``load_outcomes`` streams the raw
request facts back for re-slicing / recomputing percentiles.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from perf_harness.drive.load import LoadProfile, Pacing, Schedule, Stage
from perf_harness.metric import (
    CounterSummary,
    DistributionSummary,
    GaugeSummary,
    MetricFamily,
    MetricSummary,
    ScalarSummary,
)
from perf_harness.model import (
    Outcome,
    ProbeErrors,
    RequestStats,
    ResourceProfile,
    Run,
    Sample,
    Series,
    SloAssertion,
    SloCheck,
    StopSnapshot,
    TrialResult,
    TrialStop,
)

#: bump when run.json's shape changes incompatibly — offline readers check this first
RUN_SCHEMA = 2


# ---------------------------------------------------------------------------
# serializers (model → plain dict) and their inverses — kept adjacent per noun so
# the two directions can't drift apart silently
# ---------------------------------------------------------------------------


def _resources_json(c: ResourceProfile) -> dict:
    return {
        "cpu": c.cpu,
        "memory": c.memory,
        "workers": c.workers,
        "replicas": c.replicas,
        "extra": dict(c.extra),
        "label": c.label(),  # display convenience; derived, ignored on load
    }


def _resources_from(d: dict) -> ResourceProfile:
    return ResourceProfile(
        cpu=d.get("cpu"),
        memory=d.get("memory"),
        workers=d.get("workers"),
        replicas=int(d.get("replicas", 1)),
        extra=dict(d.get("extra") or {}),
    )


def _load_json(ld: LoadProfile) -> dict:
    return {
        "model": ld.model,
        "label": ld.label(),  # display convenience; derived, ignored on load
        "schedule": {
            "start_level": ld.schedule.start_level,
            "stages": [
                {"over_s": s.over_s, "to_level": s.to_level, "kind": s.kind, "name": s.name}
                for s in ld.schedule.stages
            ],
        },
        "pacing": {"kind": ld.pacing.kind, "secs": ld.pacing.secs, "max_secs": ld.pacing.max_secs},
        "warmup_s": ld.warmup_s,
        "max_inflight": ld.max_inflight,
        "abort_on_error_rate": ld.abort_on_error_rate,
        "breaker_min_n": ld.breaker_min_n,
        "graceful_stop_s": ld.graceful_stop_s,
    }


def _load_from(d: dict) -> LoadProfile:
    sched = d.get("schedule") or {}
    pac = d.get("pacing") or {}
    return LoadProfile(
        model=d["model"],
        schedule=Schedule(
            stages=tuple(
                Stage(
                    over_s=float(s["over_s"]),
                    to_level=float(s["to_level"]),
                    kind=s.get("kind", "ramp"),
                    name=s.get("name"),
                )
                for s in sched.get("stages", [])
            ),
            start_level=float(sched.get("start_level", 0.0)),
        ),
        pacing=Pacing(
            kind=pac.get("kind", "none"),
            secs=float(pac.get("secs", 0.0)),
            max_secs=float(pac.get("max_secs", 0.0)),
        ),
        warmup_s=float(d.get("warmup_s", 0.0)),
        max_inflight=d.get("max_inflight"),
        abort_on_error_rate=d.get("abort_on_error_rate"),
        breaker_min_n=int(d.get("breaker_min_n", 20)),
        graceful_stop_s=float(d.get("graceful_stop_s", 30.0)),
    )


def _summary_json(s: MetricSummary) -> dict:
    """Typed summary → tagged dict; the ``kind`` tag picks the inverse on load."""
    caveats = sorted(s.caveats)
    if isinstance(s, CounterSummary):
        return {"kind": "counter", "total": s.total, "rate": s.rate, "increase": s.increase,
                "caveats": caveats}  # fmt: skip
    if isinstance(s, GaugeSummary):
        return {"kind": "gauge", "last": s.last, "mean": s.mean, "peak": s.peak,
                "caveats": caveats}  # fmt: skip
    if isinstance(s, DistributionSummary):
        return {"kind": "distribution", "n": s.n, "mean": s.mean, "p50": s.p50, "p95": s.p95,
                "p99": s.p99, "caveats": caveats}  # fmt: skip
    return {"kind": "scalar", "value": s.value, "caveats": caveats}


def _summary_from(d: dict) -> MetricSummary:
    caveats = frozenset(d.get("caveats") or [])
    kind = d["kind"]
    if kind == "counter":
        return CounterSummary(
            total=d["total"], rate=d.get("rate"), increase=d.get("increase"), caveats=caveats
        )
    if kind == "gauge":
        return GaugeSummary(last=d["last"], mean=d.get("mean"), peak=d.get("peak"), caveats=caveats)
    if kind == "distribution":
        return DistributionSummary(
            n=d["n"], mean=d["mean"], p50=d["p50"], p95=d["p95"], p99=d["p99"], caveats=caveats
        )
    return ScalarSummary(value=d["value"], caveats=caveats)


def _stats_json(s: RequestStats) -> dict:
    return {
        "n": s.n,
        "n_ok": s.n_ok,
        "throughput_rps": s.throughput_rps,
        "p50_ms": s.p50_ms,
        "p95_ms": s.p95_ms,
        "p99_ms": s.p99_ms,
        "mean_ms": s.mean_ms,
        "error_rate": s.error_rate,
        "error_breakdown": dict(s.error_breakdown),
        "n_dropped": s.n_dropped,
        "caveats": sorted(s.caveats),
        "metrics": {k: _summary_json(v) for k, v in s.metrics.items()},
    }


def _stats_from(d: dict) -> RequestStats:
    return RequestStats(
        n=d["n"],
        n_ok=d["n_ok"],
        throughput_rps=d["throughput_rps"],
        p50_ms=d["p50_ms"],
        p95_ms=d["p95_ms"],
        p99_ms=d["p99_ms"],
        error_rate=d["error_rate"],
        error_breakdown=dict(d.get("error_breakdown") or {}),
        n_dropped=d.get("n_dropped", 0),
        mean_ms=d.get("mean_ms", 0.0),
        metrics={k: _summary_from(v) for k, v in (d.get("metrics") or {}).items()},
        caveats=frozenset(d.get("caveats") or []),
    )


def _family_json(f: MetricFamily) -> dict:
    return {
        "unit": f.unit,
        "side": f.side,
        "value_kind": f.value_kind,
        "source": f.source,
        "description": f.description,
        "labels": sorted(f.labels),
    }


def _family_from(name: str, d: dict) -> MetricFamily:
    return MetricFamily(
        name=name,
        unit=d.get("unit", ""),
        side=d["side"],
        value_kind=d["value_kind"],
        source=d.get("source", "client"),
        description=d.get("description", ""),
        labels=frozenset(d.get("labels") or []),
    )


def _stop_json(s: TrialStop) -> dict:
    out: dict = {
        "reason": s.reason,
        "inflight_at_stop": s.inflight_at_stop,
        "interrupted": s.interrupted,
        "force_cancelled": s.force_cancelled,
    }
    if s.snapshot:
        snap = s.snapshot
        out["snapshot"] = {
            "at_s": round(snap.at_s, 2),
            "sent": snap.sent,
            "errors": snap.errors,
            "error_rate": round(snap.error_rate, 4),
            "threshold": snap.threshold,
        }
    return out


def _stop_from(d: dict) -> TrialStop:
    snap = d.get("snapshot")
    return TrialStop(
        reason=d.get("reason", "deadline"),
        snapshot=StopSnapshot(
            at_s=snap["at_s"],
            sent=snap["sent"],
            errors=snap["errors"],
            error_rate=snap["error_rate"],
            threshold=snap["threshold"],
        )
        if snap
        else None,
        inflight_at_stop=d.get("inflight_at_stop", 0),
        interrupted=d.get("interrupted", 0),
        force_cancelled=d.get("force_cancelled", False),
    )


def _slo_json(c: SloCheck) -> dict:
    a = c.assertion
    return {
        "metric": a.metric,
        "op": a.op,
        # a `between` threshold is a (lo, hi) tuple — JSON carries it as a list
        "threshold": list(a.threshold) if isinstance(a.threshold, tuple) else a.threshold,
        "level": a.level,
        "window": a.window,
        "observed": c.observed,
        "state": c.state,
    }


def _slo_from(d: dict) -> SloCheck:
    thr = d["threshold"]
    return SloCheck(
        assertion=SloAssertion(
            metric=d["metric"],
            op=d["op"],
            threshold=tuple(thr) if isinstance(thr, list) else thr,
            level=d.get("level"),
            window=d.get("window", "measurement"),
        ),
        observed=d.get("observed"),
        state=d["state"],
    )


def _outcome_json(trial_id: str, t: float, o: Outcome) -> dict:
    return {
        "trial": trial_id,
        "t": round(t, 3),
        "status": o.status,
        "duration_ms": o.duration_ms,
        "ok": o.ok,
        "error_kind": o.error_kind,
        "events": o.events,
        "nbytes": o.nbytes,
        "dropped": o.dropped,
        "stage": o.stage,
        "facets": dict(o.facets),
        "metrics": dict(o.metrics),
        "meta": o.meta,
    }


def _outcome_from(d: dict) -> tuple[str, float, Outcome]:
    return (
        d["trial"],
        d["t"],
        Outcome(
            status=d.get("status"),
            duration_ms=d.get("duration_ms", 0.0),
            ok=d.get("ok", False),
            error_kind=d.get("error_kind"),
            events=d.get("events", 0),
            nbytes=d.get("nbytes", 0),
            metrics=dict(d.get("metrics") or {}),
            dropped=d.get("dropped", False),
            stage=d.get("stage"),
            meta=d.get("meta") or {},
            facets=dict(d.get("facets") or {}),
        ),
    )


def _trial_json(r: TrialResult) -> dict:
    return {
        "id": r.label(),
        "subject": r.subject,
        "resources": _resources_json(r.resources),
        "load": _load_json(r.load),
        "stop": _stop_json(r.stop),
        "cooldown_start_s": r.cooldown_start_s,
        "slo": [_slo_json(c) for c in r.slo],
        "registry": {name: _family_json(f) for name, f in r.metrics.items()},
        "request": {
            "overall": _stats_json(r.overall),
            "by_facet": {
                k: {v: _stats_json(s) for v, s in vals.items()} for k, vals in r.by_facet.items()
            },
            "by_stage": {k: _stats_json(s) for k, s in r.by_stage.items()},
        },
        "probe_metrics": {sid: _summary_json(s) for sid, s in r.probe_metrics.items()},
        "probe_errors": {
            name: {"failures": e.failures, "ticks": e.ticks, "last": e.last}
            for name, e in r.probe_errors.items()
        },
    }


def _trial_from(d: dict, subject: str) -> TrialResult:
    req = d.get("request") or {}
    return TrialResult(
        subject=d.get("subject", subject),
        resources=_resources_from(d["resources"]),
        load=_load_from(d["load"]),
        overall=_stats_from(req["overall"]),
        by_facet={
            k: {v: _stats_from(s) for v, s in vals.items()}
            for k, vals in (req.get("by_facet") or {}).items()
        },
        series={},  # filled from timeseries.csv by load_run
        by_stage={k: _stats_from(s) for k, s in (req.get("by_stage") or {}).items()},
        stop=_stop_from(d.get("stop") or {}),
        cooldown_start_s=d.get("cooldown_start_s"),
        slo=[_slo_from(c) for c in d.get("slo") or []],
        probe_metrics={sid: _summary_from(s) for sid, s in (d.get("probe_metrics") or {}).items()},
        metrics={name: _family_from(name, f) for name, f in (d.get("registry") or {}).items()},
        probe_errors={
            name: ProbeErrors(
                failures=e.get("failures", 0), ticks=e.get("ticks", 0), last=e.get("last", "")
            )
            for name, e in (d.get("probe_errors") or {}).items()
        },
    )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def write_run_data(run: Run, run_dir: str | Path) -> dict[str, str]:
    """Write the raw + model layers under ``run_dir``: ``run.json`` (the full Run)
    and ``outcomes.jsonl`` (per-request facts). ``timeseries.csv`` — the other raw
    artifact — is written by ``write_report`` alongside the views (same content
    either way; one writer). Returns artifact paths."""
    out = Path(run_dir)
    out.mkdir(parents=True, exist_ok=True)

    doc = {
        "schema": RUN_SCHEMA,
        "run_id": run.run_id,
        "experiment": run.experiment,
        "created_at": run.created_at,
        "subject": run.subject,
        "passed": run.passed,
        "n_trials": len(run.trials),
        "trials": [_trial_json(r) for r in run.trials],
    }
    run_json = out / "run.json"
    run_json.write_text(json.dumps(doc, ensure_ascii=False, indent=2))

    outcomes = out / "outcomes.jsonl"
    with outcomes.open("w") as f:
        for r in run.trials:
            tid = r.label()
            for t, o in r.outcomes:
                # default=str: meta is a free-form dict (judge signals) — never let one
                # exotic value lose the whole raw layer
                f.write(json.dumps(_outcome_json(tid, t, o), ensure_ascii=False, default=str))
                f.write("\n")

    return {"run.json": str(run_json), "outcomes": str(outcomes)}


def load_run(run_dir: str | Path, *, with_series: bool = True) -> Run:
    """Reconstruct a ``Run`` from a run dir — the model layer back in memory, so
    ``MetricStore(load_run(d).trials)`` serves the same ``<family>{labels}.<stat>``
    reads offline. ``with_series`` also reads ``timeseries.csv`` back into each
    trial's ``series`` (units resolved from the trial's registry); raw outcomes are
    NOT loaded here (see ``load_outcomes``)."""
    out = Path(run_dir)
    doc = json.loads((out / "run.json").read_text())
    schema = doc.get("schema")
    if schema != RUN_SCHEMA:
        raise ValueError(
            f"run.json schema {schema!r} not supported (expected {RUN_SCHEMA}); "
            f"re-run with a matching perf_harness or read the file directly"
        )
    subject = doc.get("subject", "")
    trials = [_trial_from(d, subject) for d in doc.get("trials") or []]

    ts = out / "timeseries.csv"
    if with_series and ts.exists():
        by_id = {r.label(): r for r in trials}
        with ts.open() as f:
            for row in csv.DictReader(f):
                r = by_id.get(row["trial"])
                if r is None:
                    continue
                sid = row["series"]
                series = r.series.get(sid)
                if series is None:
                    # unit lives on the family (label-free) — derive family from the sid
                    fam = r.metrics.get(sid.split("{", 1)[0])
                    series = r.series[sid] = Series(metric=sid, unit=fam.unit if fam else "")
                series.samples.append(Sample(t=float(row["t"]), value=float(row["value"])))

    return Run(
        run_id=doc["run_id"],
        experiment=doc["experiment"],
        created_at=doc.get("created_at", ""),
        subject=subject,
        trials=trials,
        passed=bool(doc.get("passed", True)),
    )


def load_outcomes(run_dir: str | Path) -> dict[str, list[tuple[float, Outcome]]]:
    """Read ``outcomes.jsonl`` back: trial id → ``[(t, Outcome), …]`` in record order.
    The raw request layer — re-slice, recompute percentiles, or re-judge offline."""
    out: dict[str, list[tuple[float, Outcome]]] = {}
    path = Path(run_dir) / "outcomes.jsonl"
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            tid, t, o = _outcome_from(json.loads(line))
            out.setdefault(tid, []).append((t, o))
    return out

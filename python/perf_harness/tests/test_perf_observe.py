"""observe: — the one key for per-service resource observation (Subject + downstream).

client (load-gen inflight/sent) is always recorded; there is no top-level probes:.
"""

import json
from types import SimpleNamespace

import pytest

from perf_harness.config import load_experiment
from perf_harness.drive.load import LoadProfile, Schedule
from perf_harness.drive.workload import Workload
from perf_harness.engine import Engine, Experiment, Subject
from perf_harness.metric import (
    GaugeSummary,
    series_id,
    split_ref,
    split_series,
)
from perf_harness.model import K8sRef, Outcome, ResourceProfile, Target
from perf_harness.observe import (
    DeriveSpec,
    FamilySpec,
    KubectlTopProbe,
    Probe,
    ResourceLimitsProbe,
)

_SUBJECT = (
    "name: x\n"
    "subject: { name: chat, base_url: 'http://x:8001',\n"
    "  k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=chat } }\n"
    "resources: [ {} ]\n"
    "workload: { name: mock }\n"
    "load: { model: closed, levels: [1], ramp_s: 0, steady_s: 0.2 }\n"
)


def test_k8s_probe_binds_to_service_as_a_label():
    ref = K8sRef(kubeconfig="/kc", namespace="ns", app_label="app=planit")
    p = KubectlTopProbe(k8s=ref, service="planit")
    assert p.name == "top.planit"  # unique store id (one per observed target)
    assert p.family == "top" and p.labels == {"service": "planit"}  # service is a LABEL
    assert p._k8s is ref
    descs = p.describe()
    # describe() returns the FAMILY (label-free); the concrete series id is built from
    # family + the probe's labels (service lives on the series, not the family)
    assert {d.name for d in descs} == {"top.cpu_m", "top.mem_mi"}
    assert {series_id(d.name, p.labels) for d in descs} == {
        'top.cpu_m{service="planit"}',
        'top.mem_mi{service="planit"}',
    }
    assert all(d.side == "resource" and d.source == "k8s" for d in descs)
    # unbound probe keeps the bare name and falls back to the Subject's k8s
    bare = KubectlTopProbe()
    assert bare.name == "top" and bare._k8s is None


def test_observe_is_the_one_shape_with_client_always_on(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - { name: chat, probes: [metrics, top, rss] }\n"  # Subject: no k8s → its own pod + /metrics
        "  - { name: planit, k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=planit }, probes: [top, rss] }\n"
        "  - { name: executor, k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=exec }, probes: [top] }\n"
    )
    exp, _ = load_experiment(str(cfg))
    by_name = {p.name: p for p in exp.probes}
    # client is auto-prepended (always on); every observed probe is service-prefixed
    assert [p.name for p in exp.probes] == [
        "client",
        "metrics.chat",
        "top.chat",
        "rss.chat",
        "top.planit",
        "rss.planit",
        "top.executor",
    ]
    assert by_name["top.chat"]._k8s is None  # Subject entry → falls back at sample time
    assert by_name["top.planit"]._k8s.app_label == "app=planit"


def test_probes_key_is_removed(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_SUBJECT + "probes: [client, top]\n")
    try:
        load_experiment(str(cfg))
    except ValueError as e:
        assert "probes" in str(e) and "observe" in str(e)
    else:
        raise AssertionError("expected ValueError: probes: was removed")


def test_observe_metrics_only_on_subject(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - { name: planit, k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=planit }, probes: [metrics] }\n"
    )
    try:
        load_experiment(str(cfg))
    except ValueError as e:
        assert "metrics" in str(e) and "Subject" in str(e)
    else:
        raise AssertionError("expected ValueError: downstream metrics unsupported")


def test_observe_rejects_unknown_probe(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - { name: planit, k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=planit }, probes: [client] }\n"
    )
    try:
        load_experiment(str(cfg))
    except ValueError as e:
        assert "client" in str(e)
    else:
        raise AssertionError("expected ValueError for a non-service probe in observe")


def test_slo_service_label_only_on_time_sampled(tmp_path):
    """A `service` label belongs to a resource (time_sampled) series only — never a
    request slice. The family-keyed registry no longer fail-fasts these for free, so
    _validate_slo pins the rule down explicitly (else they'd silently go missing or
    crash the resolver)."""
    base = _SUBJECT + "observe:\n  - { name: chat, probes: [top] }\n"

    def cfg(metric: str) -> str:
        c = tmp_path / "c.yaml"
        # single-quote the metric: it carries `{...}` and `"` that YAML flow syntax
        # would otherwise choke on
        c.write_text(base + f"slo: [ {{ metric: '{metric}', lt: 100 }} ]\n")
        return str(c)

    # valid: a resource metric with a service label + an explicit stat
    exp, _ = load_experiment(cfg('top.cpu_m{service="chat"}.peak'))
    assert exp.slo[0].metric == 'top.cpu_m{service="chat"}.peak'

    # a request (derived) metric can NOT carry a service label
    with pytest.raises(ValueError, match="service"):
        load_experiment(cfg('request.duration_ms{service="chat"}.p99'))

    # a builtin alias + service (no stat) is rejected too (would crash the resolver)
    with pytest.raises(ValueError, match="service"):
        load_experiment(cfg('p99_ms{service="chat"}'))

    # an unobserved service value still fails
    with pytest.raises(ValueError, match="not observed"):
        load_experiment(cfg('top.cpu_m{service="planit"}.peak'))


def test_resource_limits_probe_describes_request_and_limit_gauges():
    # request/limit are just metrics whose series never varies — gauges, k8s-sourced,
    # and (crucially) the SAME units as `top`, so the report overlays them as flat
    # reference lines on the cpu/mem usage charts with no special rendering.
    p = ResourceLimitsProbe(service="chat")
    assert p.family == "limits"
    descs = {d.name: d for d in p.describe()}
    assert set(descs) == {
        "limits.cpu_request",
        "limits.cpu_limit",
        "limits.mem_request",
        "limits.mem_limit",
    }
    assert all(d.value_kind == "gauge" and d.source == "k8s" for d in descs.values())
    top = KubectlTopProbe(service="chat").families  # {cpu_m: millicores, mem_mi: MiB}
    assert descs["limits.cpu_limit"].unit == top["cpu_m"].unit  # millicores → same cpu chart
    assert descs["limits.mem_limit"].unit == top["mem_mi"].unit  # MiB → same mem chart


def test_observe_wires_limits_probe(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(_SUBJECT + "observe:\n  - { name: chat, probes: [top, limits] }\n")
    exp, _ = load_experiment(str(cfg))
    assert "limits.chat" in [p.name for p in exp.probes]  # service-bound limits probe wired


def test_series_id_is_prometheus_form():
    assert series_id("top.cpu_m", {}) == "top.cpu_m"
    assert series_id("top.cpu_m", {"service": "chat"}) == 'top.cpu_m{service="chat"}'


def test_resolver_splits_labeled_series_id():
    # the stat is still the last dotted segment, so the resolver works on labeled ids
    name, stat = split_ref('top.cpu_m{service="planit"}.peak')
    assert name == 'top.cpu_m{service="planit"}' and stat == "peak"


def test_store_pivot_groups_by_service_label():
    # the group-by-label read every consumer uses (analysis peaks, §3 curves):
    # one summary per service for a family
    from perf_harness.metric.store import MetricStore

    pm = {
        'top.cpu_m{service="chat"}': GaugeSummary(last=300, mean=250, peak=305),
        'top.cpu_m{service="planit"}': GaugeSummary(last=460, mean=420, peak=467),
    }
    r = SimpleNamespace(probe_metrics=pm, metrics={})
    out = MetricStore([]).pivot(r, "top.cpu_m", "service")
    assert {svc: s.peak for svc, s in out.items()} == {"chat": 305, "planit": 467}


def test_store_pivot_keeps_per_pod_entities_distinct():
    # per_pod adds a {pod} label; the pivot must not drop or merge those series —
    # each pod is its own entity, keyed "service/pod"
    from perf_harness.metric.store import MetricStore

    pm = {
        'top.cpu_m{pod="chat-a",service="chat"}': GaugeSummary(last=1, peak=305),
        'top.cpu_m{pod="chat-b",service="chat"}': GaugeSummary(last=1, peak=467),
    }
    r = SimpleNamespace(probe_metrics=pm, metrics={})
    out = MetricStore([]).pivot(r, "top.cpu_m", "service")
    assert {svc: s.peak for svc, s in out.items()} == {
        "chat/chat-a": 305,
        "chat/chat-b": 467,
    }


def test_split_series_is_series_id_inverse():
    assert split_series('cpu_m{pod="a",service="chat"}') == (
        "cpu_m",
        {"pod": "a", "service": "chat"},
    )
    # a dotted bare name has no stat to mis-split (unlike parse_ref on a ref)
    assert split_series("client.inflight") == ("client.inflight", {})


async def test_top_probe_per_pod_emits_labeled_keys(monkeypatch):
    async def fake_run(cmd):  # two replicas in the `kubectl top pod -l …` output
        return "chat-abc 850m 1234Mi\nchat-def 150m 766Mi\n"

    monkeypatch.setattr("perf_harness.observe.k8s.run_capture", fake_run)
    ref = K8sRef(kubeconfig="/kc", namespace="ns", app_label="app=chat")
    p = KubectlTopProbe(k8s=ref, service="chat", per_pod=True)
    out = await p.sample(SimpleNamespace(target=SimpleNamespace(k8s=None)))
    # one {pod}-labeled key per replica — NOT the summed cpu_m/mem_mi
    assert out == {
        'cpu_m{pod="chat-abc"}': 850.0,
        'mem_mi{pod="chat-abc"}': 1234.0,
        'cpu_m{pod="chat-def"}': 150.0,
        'mem_mi{pod="chat-def"}': 766.0,
    }


async def test_limits_probe_per_pod_and_summed_share_one_source(monkeypatch):
    j = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "chat-abc"},
                    "spec": {"containers": [{"resources": {"limits": {"cpu": "1"}}}]},
                },
                {
                    "metadata": {"name": "chat-def"},
                    "spec": {"containers": [{"resources": {"limits": {"cpu": "2"}}}]},
                },
            ]
        }
    )

    async def fake_run(cmd):
        return j

    monkeypatch.setattr("perf_harness.observe.k8s.run_capture", fake_run)
    ref = K8sRef(kubeconfig="/kc", namespace="ns", app_label="app=chat")
    ctx = SimpleNamespace(target=SimpleNamespace(k8s=None))
    per_pod = await ResourceLimitsProbe(k8s=ref, service="chat", per_pod=True).sample(ctx)
    assert per_pod == {
        'cpu_limit{pod="chat-abc"}': 1000.0,
        'cpu_limit{pod="chat-def"}': 2000.0,
    }
    # summed = sum of the same per-pod parse (the service-level total)
    summed = await ResourceLimitsProbe(k8s=ref, service="chat").sample(ctx)
    assert summed == {"cpu_limit": 3000.0}


class _FanProbe(Probe):
    """A probe whose sample keys carry a {pod} label — the fan-out contract."""

    name = "fan"
    source = "k8s"
    _service = "chat"
    families = {"cpu_m": FamilySpec("millicores")}

    async def sample(self, ctx):
        return {
            series_id("cpu_m", {"pod": "p0"}): 100.0,
            series_id("cpu_m", {"pod": "p1"}): 200.0,
        }


class _NoopWL(Workload):
    name = "noop"

    async def fire(self, target, client, case, run_id):
        return Outcome(status=200, duration_ms=1.0)


async def test_engine_fans_pod_labeled_keys_into_per_pod_series():
    exp = Experiment(
        subject=Subject("m", Target(base_url="http://127.0.0.1:0")),
        workload=_NoopWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(2, 0.0, 0.2))],
        probes=[_FanProbe()],
    )
    r = (await Engine(exp).run()).trials[0]
    # each pod becomes its own series, base {service} merged with the key's {pod}
    # (plus the synthesized health series at the probe's base label-set)
    sids = {sid for sid in r.series if sid.startswith("fan.")}
    assert sids == {
        'fan.cpu_m{pod="p0",service="chat"}',
        'fan.cpu_m{pod="p1",service="chat"}',
        'fan.up{service="chat"}',
    }
    # …and its own summary (constant gauges → peak == the per-pod constant)
    assert r.probe_metrics['fan.cpu_m{pod="p0",service="chat"}'].peak == 100.0
    assert r.probe_metrics['fan.cpu_m{pod="p1",service="chat"}'].peak == 200.0
    # the registry stays family-keyed — pod is a label, not a new family
    assert r.metrics["fan.cpu_m"].side == "resource"


def test_slo_service_gate_fails_fast_under_per_pod(tmp_path):
    # per_pod emits only {pod,service} series — a {service="…"} gate would resolve
    # Missing → skipped on EVERY run (and strict_slo defaults false, so an existing CI
    # gate would silently stop gating). That must be a config-time error, not a skip.
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n  - { name: chat, probes: [top], per_pod: true }\n"
        "slo: [ { metric: 'top.cpu_m{service=\"chat\"}.peak', lt: 100 } ]\n"
    )
    with pytest.raises(ValueError, match="per_pod"):
        load_experiment(str(cfg))


def test_observe_per_pod_wires_the_flag(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n  - { name: chat, probes: [top, limits], per_pod: true }\n"
    )
    exp, _ = load_experiment(str(cfg))
    by_name = {p.name: p for p in exp.probes}
    assert by_name["top.chat"]._per_pod and by_name["limits.chat"]._per_pod


async def test_metrics_probe_scrape_extra_families():
    # scrape: arbitrary exposition families ride the same /metrics fetch and enter
    # the same metric model — builtins are just canned specs of the same mechanism
    import httpx

    from perf_harness.observe import MetricsScrapeProbe, ScrapeSpec

    text = (
        "chat_requests_total 50\n"
        "chat_requests_in_progress 3\n"
        'gen_ai_server_request_duration_seconds_count{gen_ai_operation_name="chat",error_type=""} 90\n'
        'gen_ai_server_request_duration_seconds_count{gen_ai_operation_name="chat",error_type="X"} 10\n'
        'gen_ai_server_request_duration_seconds_sum{gen_ai_operation_name="chat",error_type=""} 540.0\n'
    )

    def handler(_request):
        return httpx.Response(200, content=text.encode())

    p = MetricsScrapeProbe(
        prefix="chat",
        service="chat",
        scrape=[
            ScrapeSpec(
                source="gen_ai_server_request_duration_seconds_count",
                name="sse_streams",
            ),
            ScrapeSpec(
                source="gen_ai_server_request_duration_seconds_count",
                name="sse_errors",
                drop={"error_type": ("", "client_disconnect")},
            ),
        ],
    )
    # the extra families join the probe's declared vocabulary (units + value kinds)
    assert (
        p.families["sse_streams"].unit == "count"
        and p.families["sse_errors"].value_kind == "counter"
    )
    assert {d.name for d in p.describe()} >= {
        "metrics.sse_streams",
        "metrics.sse_errors",
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ctx = SimpleNamespace(
            target=SimpleNamespace(base_url="http://x", k8s=None), probe_client=client
        )
        out = await p.sample(ctx)
    assert out == {
        "req_total": 50.0,
        "in_progress": 3.0,
        "sse_streams": 100.0,
        "sse_errors": 10.0,
    }


async def test_metrics_probe_scrape_by_emits_labeled_series():
    # `by`: one series_id-keyed reading per distinct label value — the Engine
    # groups labeled keys per extra-label-set exactly like per_pod series
    import httpx

    from perf_harness.observe import MetricsScrapeProbe, ScrapeSpec

    text = (
        'control_requests_total{path="/v1/bots",method="POST",status_code="200"} 30\n'
        'control_requests_total{path="/v1/bots",method="GET",status_code="200"} 12\n'
        'control_requests_total{path="/v1/configs",method="POST",status_code="200"} 7\n'
    )

    def handler(_request):
        return httpx.Response(200, content=text.encode())

    p = MetricsScrapeProbe(
        service="control",
        scrape=[
            ScrapeSpec(source="control_requests_total", name="ctl_requests", by=("path",)),
        ],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ctx = SimpleNamespace(
            target=SimpleNamespace(base_url="http://x", k8s=None), probe_client=client
        )
        out = await p.sample(ctx)
    assert out == {
        'ctl_requests{path="/v1/bots"}': 42.0,
        'ctl_requests{path="/v1/configs"}': 7.0,
    }


def test_observe_scrape_wires_specs(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics, top]\n"
        "    scrape:\n"
        "      - { from: gen_ai_server_request_duration_seconds_count, as: sse_streams }\n"
        "      - from: gen_ai_server_request_duration_seconds_count\n"
        "        as: sse_errors\n"
        "        drop: { error_type: ['', client_disconnect] }\n"
    )
    exp, _ = load_experiment(str(cfg))
    probe = next(p for p in exp.probes if p.name == "metrics.chat")
    assert [s.name for s in probe.scrape] == ["sse_streams", "sse_errors"]
    assert probe.scrape[1].drop == {"error_type": ("", "client_disconnect")}
    # …and the families are SLO-addressable like any declared metric
    cfg2 = tmp_path / "c2.yaml"
    cfg2.write_text(
        cfg.read_text()
        + "slo: [ { metric: 'metrics.sse_errors{service=\"chat\"}.increase', lt: 5 } ]\n"
    )
    exp2, _ = load_experiment(str(cfg2))
    assert exp2.slo[0].metric == 'metrics.sse_errors{service="chat"}.increase'


def test_observe_scrape_by_parses_and_blocks_derive(tmp_path):
    # `by`: a bare label name normalizes to a 1-tuple, a list keeps order
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape:\n"
        "      - { from: control_requests_total, as: ctl_requests, by: path }\n"
        "      - { from: x_total, as: x_by_two, by: [method, path] }\n"
    )
    exp, _ = load_experiment(str(cfg))
    probe = next(p for p in exp.probes if p.name == "metrics.chat")
    assert probe.scrape[0].by == ("path",)
    assert probe.scrape[1].by == ("method", "path")
    # malformed `by` fails at parse time, not silently at sample time
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape: [ { from: x_total, as: x, by: [] } ]\n"
    )
    with pytest.raises(ValueError, match="`by` must be a label name"):
        load_experiment(str(bad))
    # derived joins num/den per label set — a mixed pair (one by'd, one plain)
    # would silently find no matching denominator, so it fail-fasts…
    derived = tmp_path / "derived.yaml"
    derived.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape:\n"
        "      - { from: x_sum, as: xs, by: path }\n"
        "      - { from: x_count, as: xn }\n"
        "derived: [ { as: x_mean, ratio: [metrics.xs, metrics.xn] } ]\n"
    )
    with pytest.raises(ValueError, match="share the same `by`"):
        load_experiment(str(derived))
    # …while a same-by pair parses: one derived ratio per label value (per-path mean)
    matched = tmp_path / "matched.yaml"
    matched.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape:\n"
        "      - { from: x_sum, as: xs, by: path }\n"
        "      - { from: x_count, as: xn, by: path }\n"
        "derived: [ { as: x_mean, ratio: [metrics.xs, metrics.xn] } ]\n"
    )
    exp2, _ = load_experiment(str(matched))
    assert [d.name for d in exp2.derived] == ["x_mean"]


def test_observe_scrape_requires_metrics_probe(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [top]\n"
        "    scrape: [ { from: x_total } ]\n"
    )
    with pytest.raises(ValueError, match="metrics"):
        load_experiment(str(cfg))


async def test_scrape_http_error_raises_not_empty():
    # a 500 body must NOT parse as "no data" — it raises, the Engine records a
    # probe_error (observability failure is a fact, not an empty reading)
    import httpx

    from perf_harness.observe import MetricsScrapeProbe

    def handler(_request):
        return httpx.Response(500, content=b"boom")

    p = MetricsScrapeProbe(prefix="chat", service="chat")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ctx = SimpleNamespace(
            target=SimpleNamespace(base_url="http://x", k8s=None), probe_client=client
        )
        with pytest.raises(httpx.HTTPStatusError):
            await p.sample(ctx)


class _FlakyProbe(Probe):
    """Fails every tick — the observation-failure census must surface it."""

    name = "flaky.chat"
    source = "http"
    _service = "chat"

    families = {"x": FamilySpec("count")}

    @property
    def family(self) -> str:
        return "flaky"

    async def sample(self, ctx):
        raise RuntimeError("metrics endpoint down")


async def test_probe_errors_flow_to_trial_and_store():
    from perf_harness.metric import Missing
    from perf_harness.metric.store import MetricStore

    exp = Experiment(
        subject=Subject("m", Target(base_url="http://127.0.0.1:0")),
        workload=_NoopWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.2))],
        probes=[_FlakyProbe()],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    pe = r.probe_errors["flaky.chat"]
    assert pe.failures == pe.ticks >= 1 and "down" in pe.last
    # an absent read on an errored probe is Missing(probe_error) — NOT "no slice"
    read = MetricStore([r]).query(r, 'flaky.x{service="chat"}.peak')
    assert isinstance(read, Missing) and read.reason == "probe_error"


class _CountingProbe(Probe):
    """Counters climbing linearly — feeds the derive ratio end-to-end."""

    name = "metrics.chat"
    source = "http"
    _service = "chat"
    families = {
        "ttft_sum": FamilySpec("s", "counter"),
        "ttft_n": FamilySpec("count", "counter"),
    }

    def __init__(self):
        self._tick = 0

    @property
    def family(self) -> str:
        return "metrics"

    async def sample(self, ctx):
        self._tick += 1
        # each tick: +2 streams, +0.5s of ttft → mean ttft = 0.25s
        return {"ttft_sum": 0.5 * self._tick, "ttft_n": 2.0 * self._tick}


async def test_derive_ratio_computed_per_trial():
    exp = Experiment(
        subject=Subject("m", Target(base_url="http://127.0.0.1:0")),
        workload=_NoopWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.3))],
        probes=[_CountingProbe()],
        derived=[
            DeriveSpec(name="ttft_mean_s", num="metrics.ttft_sum", den="metrics.ttft_n", unit="s")
        ],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    sid = series_id("ttft_mean_s", {"service": "chat"})
    assert abs(r.probe_metrics[sid].value - 0.25) < 1e-9  # Δsum ÷ Δn over the window
    fam = r.metrics["ttft_mean_s"]
    assert fam.side == "resource" and fam.value_kind == "scalar" and fam.unit == "s"


class _GroupCountingProbe(Probe):
    """by:-grouped counters (two paths) — feeds the PER-GROUP derive ratio."""

    name = "metrics.control"
    source = "http"
    _service = "control"
    families = {
        "d_sum": FamilySpec("s", "counter"),
        "d_n": FamilySpec("count", "counter"),
    }

    def __init__(self):
        self._tick = 0

    @property
    def family(self) -> str:
        return "metrics"

    async def sample(self, ctx):
        self._tick += 1
        t = self._tick
        return {
            # /a: mean 0.5s per request; /b: mean 2.0s per request
            series_id("d_sum", {"path": "/a"}): 1.0 * t,
            series_id("d_n", {"path": "/a"}): 2.0 * t,
            series_id("d_sum", {"path": "/b"}): 4.0 * t,
            series_id("d_n", {"path": "/b"}): 2.0 * t,
        }


async def test_derive_ratio_computed_per_label_group():
    exp = Experiment(
        subject=Subject("m", Target(base_url="http://127.0.0.1:0")),
        workload=_NoopWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.3))],
        probes=[_GroupCountingProbe()],
        derived=[DeriveSpec(name="d_mean_s", num="metrics.d_sum", den="metrics.d_n", unit="s")],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    a = r.probe_metrics[series_id("d_mean_s", {"path": "/a", "service": "control"})]
    b = r.probe_metrics[series_id("d_mean_s", {"path": "/b", "service": "control"})]
    assert abs(a.value - 0.5) < 1e-9 and abs(b.value - 2.0) < 1e-9
    fam = r.metrics["d_mean_s"]
    assert fam.side == "resource" and fam.value_kind == "scalar"


def test_observe_derive_and_metrics_url_config(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape:\n"
        "      - { from: x_seconds_sum, as: x_sum, unit: s }\n"
        "      - { from: x_seconds_count, as: x_n }\n"
        "  - name: planit\n"
        "    k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=planit }\n"
        "    probes: [metrics, top]\n"
        "    metrics_url: http://10.0.0.2:8000/metrics\n"
        "derived: [ { as: x_mean_s, ratio: [metrics.x_sum, metrics.x_n], unit: s } ]\n"
        "slo: [ { metric: 'x_mean_s{service=\"chat\"}.value', lt: 1 } ]\n"
    )
    exp, _ = load_experiment(str(cfg))
    assert [d.name for d in exp.derived] == ["x_mean_s"]
    planit = next(p for p in exp.probes if p.name == "metrics.planit")
    assert planit._url == "http://10.0.0.2:8000/metrics"
    # the derived scalar is SLO-addressable (declared in the static registry)
    assert exp.slo[0].metric == 'x_mean_s{service="chat"}.value'


def test_observe_metrics_downstream_requires_url(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: planit\n"
        "    k8s: { kubeconfig: ~/.kube/d, namespace: ns, app_label: app=planit }\n"
        "    probes: [metrics]\n"
    )
    with pytest.raises(ValueError, match="metrics_url"):
        load_experiment(str(cfg))


def test_derived_rejects_unknown_counter(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - { name: chat, probes: [metrics] }\n"
        "derived: [ { as: bad, ratio: [nope, also_nope] } ]\n"
    )
    with pytest.raises(ValueError, match="counter"):
        load_experiment(str(cfg))


def test_observe_entry_derive_is_a_migration_error(tmp_path):
    # the old per-entry derive: must point at the top-level key, not silently parse
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    derive: [ { as: bad, ratio: [x, y] } ]\n"
    )
    with pytest.raises(ValueError, match="TOP-LEVEL"):
        load_experiment(str(cfg))


async def test_up_series_synthesized_per_probe():
    # the Prometheus `up` analogue: health is a SERIES (when did it break), not just
    # the trial census. Healthy probe → all 1s; flaky probe → 0s and mean < 1.
    exp = Experiment(
        subject=Subject("m", Target(base_url="http://127.0.0.1:0")),
        workload=_NoopWL(),
        resources=[ResourceProfile()],
        loads=[LoadProfile(model="closed", schedule=Schedule.ramp_hold(1, 0.0, 0.2))],
        probes=[_FanProbe(), _FlakyProbe()],
        observe_interval_s=0.05,
    )
    r = (await Engine(exp).run()).trials[0]
    healthy = r.probe_metrics[series_id("fan.up", {"service": "chat"})]
    assert healthy.mean == 1.0 and healthy.peak == 1.0
    broken = r.probe_metrics[series_id("flaky.up", {"service": "chat"})]
    assert broken.mean == 0.0  # every tick failed
    assert all(s.value == 0.0 for s in r.series[series_id("flaky.up", {"service": "chat"})].samples)
    assert r.metrics["flaky.up"].value_kind == "gauge"  # registered family


def test_scrape_may_not_shadow_up(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n"
        "  - name: chat\n"
        "    probes: [metrics]\n"
        "    scrape: [ { from: x_total, as: up } ]\n"
    )
    with pytest.raises(ValueError, match="up"):
        load_experiment(str(cfg))


def test_up_is_slo_addressable(tmp_path):
    # observation availability can gate — explicitly, like everything observational
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        _SUBJECT + "observe:\n  - { name: chat, probes: [top] }\n"
        "slo: [ { metric: 'top.up{service=\"chat\"}.mean', gte: 0.99 } ]\n"
    )
    exp, _ = load_experiment(str(cfg))
    assert exp.slo[0].metric == 'top.up{service="chat"}.mean'


def test_limits_colors_are_report_palette():
    # chart colors are report-side display policy, never model metadata: the limits
    # reference lines pin limit=red / request=orange; everything else rotates
    from perf_harness.report import family_color

    assert family_color("limits.cpu_limit") == "#d62728"
    assert family_color("limits.mem_limit") == "#d62728"
    assert family_color("limits.cpu_request") == "#ff7f0e"
    assert family_color("top.cpu_m") == ""

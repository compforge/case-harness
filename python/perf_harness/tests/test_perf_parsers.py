import json

from perf_harness.observe import prom_sum
from perf_harness.observe.k8s import (
    _parse_cpu_m,
    _parse_mem_mi,
    parse_kubectl_top,
    parse_kubectl_top_per_pod,
    parse_pod_resources,
    parse_ps_rss,
)


def test_parse_cpu_m():
    assert _parse_cpu_m("500m") == 500.0
    assert _parse_cpu_m("2") == 2000.0
    assert _parse_cpu_m("1.5") == 1500.0
    assert _parse_cpu_m("") is None and _parse_cpu_m("bad") is None


def test_parse_mem_mi():
    assert _parse_mem_mi("2Gi") == 2048.0
    assert _parse_mem_mi("512Mi") == 512.0
    assert _parse_mem_mi("1Gi") == 1024.0  # "Gi" matched before "G"
    assert _parse_mem_mi(str(1024 * 1024)) == 1.0  # bare bytes → MiB
    assert _parse_mem_mi("") is None and _parse_mem_mi("bad") is None


def test_parse_kubectl_top():
    cpu, mem = parse_kubectl_top("chat-server-abc123   850m   1234Mi\n")
    assert cpu == 850.0
    assert mem == 1234.0


def test_parse_kubectl_top_empty():
    assert parse_kubectl_top("") == (None, None)


def test_parse_kubectl_top_per_pod_and_summed_agree():
    text = "chat-abc   850m   1234Mi\nchat-def   150m   766Mi\n"
    per = parse_kubectl_top_per_pod(text)
    assert per == {"chat-abc": (850.0, 1234.0), "chat-def": (150.0, 766.0)}
    # the summed view derives from the same per-pod rows — they can't disagree
    assert parse_kubectl_top(text) == (1000.0, 2000.0)
    assert parse_kubectl_top_per_pod("") == {}


def test_parse_pod_resources():
    j = json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": "chat-abc"},
                    "spec": {
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "500m", "memory": "1Gi"},
                                    "limits": {"cpu": "1", "memory": "2Gi"},
                                }
                            },
                            # sidecar with requests only — its cpu still counts there
                            {"resources": {"requests": {"cpu": "100m"}}},
                        ]
                    },
                },
                # nothing set on any container → the pod is omitted entirely
                {
                    "metadata": {"name": "chat-def"},
                    "spec": {"containers": [{"resources": {}}]},
                },
            ]
        }
    )
    out = parse_pod_resources(j)
    assert out == {
        "chat-abc": {
            "cpu_request": 600.0,
            "mem_request": 1024.0,
            "cpu_limit": 1000.0,
            "mem_limit": 2048.0,
        }
    }
    assert parse_pod_resources("not json") == {}  # probe skips itself this tick


def test_parse_ps_rss():
    text = (
        "  PID   RSS COMMAND\n"
        "    1   1024 /usr/bin/python3 -m uvicorn main:create_app --factory --workers 2\n"
        "    7 460800 python3 -c from multiprocessing.spawn import spawn_main; spawn_main()\n"
        "    8 471040 python3 -c from multiprocessing.spawn import spawn_main; spawn_main()\n"
    )
    n_workers, rss_mi = parse_ps_rss(text)
    assert n_workers == 2
    assert abs(rss_mi - (1024 + 460800 + 471040) / 1024.0) < 0.1


def test_prom_sum():
    text = (
        "# HELP chat_requests_total total\n"
        "# TYPE chat_requests_total counter\n"
        'chat_requests_total{path="/a",method="POST",status_code="200"} 10\n'
        'chat_requests_total{path="/b",method="GET",status_code="200"} 5\n'
        'chat_requests_in_progress{method="POST"} 3\n'
    )
    assert prom_sum(text, "chat_requests_total") == 15.0
    assert prom_sum(text, "chat_requests_in_progress") == 3.0
    assert prom_sum(text, "missing_metric") is None


def test_prom_sum_where_match_and_drop():
    # the GenAI SSE histogram shape: _count lines across (operation, error_type)
    text = (
        'gen_ai_server_request_duration_seconds_count{gen_ai_operation_name="chat",error_type=""} 90\n'
        'gen_ai_server_request_duration_seconds_count{gen_ai_operation_name="chat",error_type="client_disconnect"} 4\n'
        'gen_ai_server_request_duration_seconds_count{gen_ai_operation_name="chat",error_type="InternalError"} 6\n'
        'gen_ai_server_request_duration_seconds_sum{gen_ai_operation_name="chat",error_type=""} 540.5\n'
    )
    from perf_harness.observe import prom_sum_where

    name = "gen_ai_server_request_duration_seconds_count"
    assert prom_sum_where(text, name) == 100.0  # all label sets
    # the docstring's PromQL: errors exclude "" and client_disconnect
    assert prom_sum_where(text, name, drop={"error_type": ("", "client_disconnect")}) == 6.0
    assert prom_sum_where(text, name, match={"error_type": ""}) == 90.0
    # family present but every line filtered → 0.0 (zero errors), NOT absent
    assert prom_sum_where(text, name, match={"error_type": "nope"}) == 0.0
    assert prom_sum_where(text, "absent_family") is None


def test_prom_sum_by_groups_after_filters():
    # PromQL's `sum by (path)`: one group per distinct by-label value, summed over
    # the OTHER labels; match/drop filter FIRST, then survivors group
    from perf_harness.observe import prom_sum_by

    text = (
        'ctl_requests_total{path="/a",method="GET",status_code="200"} 10\n'
        'ctl_requests_total{path="/a",method="POST",status_code="200"} 5\n'
        'ctl_requests_total{path="/b",method="POST",status_code="200"} 7\n'
        'ctl_requests_total{path="/b",method="POST",status_code="500"} 2\n'
        "bare_total 3\n"
    )
    name = "ctl_requests_total"
    assert prom_sum_by(text, name, ("path",)) == {("/a",): 15.0, ("/b",): 9.0}
    # filters compose: drop 5xx, then group
    assert prom_sum_by(text, name, ("path",), drop={"status_code": ("500",)}) == {
        ("/a",): 15.0,
        ("/b",): 7.0,
    }
    # multi-label grouping keys follow declaration order
    assert prom_sum_by(text, name, ("method", "path"))[("POST", "/b")] == 9.0
    # a line without the by-label groups under "" (PromQL semantics)
    assert prom_sum_by(text, "bare_total", ("path",)) == {("",): 3.0}
    # absent family → None; present-but-all-filtered → no groups (NOT a 0.0 series)
    assert prom_sum_by(text, "absent_family", ("path",)) is None
    assert prom_sum_by(text, name, ("path",), match={"status_code": "404"}) == {}


def test_prom_line_parses_spec_escapes_and_timestamps():
    # exposition label values may contain commas and the escapes \\ \" \n — a naive
    # split-on-comma corrupts them (rules mirror Prometheus's own lvalReplacer);
    # an optional trailing timestamp must be ignored, not read as the value
    from perf_harness.observe import prom_sum_where

    text = (
        'errs_total{error_type="timeout, upstream",svc="a"} 3\n'
        'errs_total{error_type="code=\\"500\\"",svc="a"} 2\n'
        'errs_total{error_type="line1\\nline2",svc="a"} 1\n'
        "plain_total 7 1395066363000\n"
    )
    assert prom_sum_where(text, "errs_total") == 6.0
    assert prom_sum_where(text, "errs_total", match={"error_type": "timeout, upstream"}) == 3.0
    assert prom_sum_where(text, "errs_total", match={"error_type": 'code="500"'}) == 2.0
    assert prom_sum_where(text, "plain_total") == 7.0  # timestamp ignored

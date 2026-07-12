"""Subject — 压谁: a name, how to reach it, and (optionally) how to re-provision it.

The Provisioner is the only seam that touches the deployment substrate. It
realises a ResourceProfile on the Subject (reachability stays on
``Subject.target`` — applying a profile never changes how to reach the service).
It is OPTIONAL: no provisioner = the service is already deployed and the profiles
merely label the trials. Everything else in perf_harness is substrate-agnostic;
k8s lives here (HelmProvisioner) and in the K8s probes, nowhere else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from perf_harness.model import ResourceProfile, Target
from perf_harness.sh import run_capture


@dataclass
class Subject:
    """What gets loaded and observed: a name, how to reach it, and (optionally) the
    provisioner that realises each ResourceProfile on it.

    No provisioner = the common case: the service is already deployed (by a human /
    CI) and the profiles in ``Experiment.resources`` merely *label* the trials. A
    provisioner (helm) lets the harness sweep the profiles itself.
    """

    name: str
    target: Target
    provisioner: Provisioner | None = None


class Provisioner(ABC):
    """Realises a ResourceProfile on the Subject (and can undo it)."""

    @abstractmethod
    async def apply(self, profile: ResourceProfile) -> None:
        """Make the Subject run under ``profile`` (deployed and ready)."""

    async def teardown(self) -> None:
        """Restore the Subject to its baseline. Default: nothing to undo."""
        return None


class HelmProvisioner(Provisioner):
    """Drive a ResourceProfile via ``helm upgrade`` against a k8s release.

    ``set_paths`` maps ResourceProfile fields to chart value paths so the same
    provisioner works across services with different values.yaml shapes; the
    defaults match the AS planit/chat charts (``uvicorn.workers``,
    ``resources.limits.*``). Unknown/None fields are skipped.
    """

    DEFAULT_SET_PATHS = {
        "workers": "uvicorn.workers",
        "memory": "resources.limits.memory",
        "cpu": "resources.limits.cpu",
        "replicas": "replicaCount",
    }

    def __init__(
        self,
        *,
        release: str,
        chart_path: str,
        namespace: str,
        kubeconfig: str,
        base_values: str | None = None,
        set_paths: dict[str, str] | None = None,
        rollout_timeout_s: int = 180,
        extra_set: dict[str, str] | None = None,
    ) -> None:
        self.release = release
        self.chart_path = chart_path
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.base_values = base_values
        self.set_paths = set_paths or dict(self.DEFAULT_SET_PATHS)
        self.rollout_timeout_s = rollout_timeout_s
        self.extra_set = extra_set or {}

    def _set_args(self, profile: ResourceProfile) -> list[str]:
        sets: dict[str, str] = {}
        for field_name, path in self.set_paths.items():
            val = getattr(profile, field_name, None)
            if val is not None:
                sets[path] = str(val)
        sets.update(self.extra_set)
        sets.update(profile.extra)
        args: list[str] = []
        for path, val in sets.items():
            args += ["--set", f"{path}={val}"]
        return args

    async def apply(self, profile: ResourceProfile) -> None:
        cmd = [
            "helm",
            "--kubeconfig",
            self.kubeconfig,
            "-n",
            self.namespace,
            "upgrade",
            self.release,
            self.chart_path,
            "--reuse-values",
        ]
        if self.base_values:
            cmd += ["-f", self.base_values]
        cmd += self._set_args(profile)
        await run_capture(cmd)
        await run_capture(
            [
                "kubectl",
                "--kubeconfig",
                self.kubeconfig,
                "-n",
                self.namespace,
                "rollout",
                "status",
                f"deploy/{self.release}",
                f"--timeout={self.rollout_timeout_s}s",
            ]
        )

    async def teardown(self) -> None:
        cmd = [
            "helm",
            "--kubeconfig",
            self.kubeconfig,
            "-n",
            self.namespace,
            "upgrade",
            self.release,
            self.chart_path,
        ]
        if self.base_values:
            cmd += ["-f", self.base_values]
        await run_capture(cmd)

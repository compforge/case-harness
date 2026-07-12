"""Load a single ``experiment.yaml`` → ``Experiment``.

One entry file describes the whole run: ``evalset`` (corpus + cases, by
reference to reusable materials or inline), ``facets`` (FacetSchema overrides),
``business`` (base SUT config), ``envs`` / ``matrix`` (comparison arms),
``metrics`` and ``weights``. Cases referenced by filename are resolved under
``<materials_root>/cases/``; corpus/cases stay decoupled and reusable.

String values support ``${VAR}`` / ``${VAR:-default}`` interpolation from the
environment, so secrets (e.g. ``business.llm.api_key``) stay out of the yaml /
git — an unset var with no default fails loud rather than sending an empty value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from spec_case.model import Case, case_from_raw

from eval_harness.model.evalset import EvalSet, FacetSpec, SourceRecord
from eval_harness.model.experiment import Env, Experiment, Target

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate(obj: Any) -> Any:
    """Recursively resolve ``${VAR}`` / ``${VAR:-default}`` from the environment."""
    if isinstance(obj, str):

        def _repl(m: re.Match) -> str:
            var, default = m.group(1), m.group(2)
            if var in os.environ:
                return os.environ[var]
            if default is not None:
                return default
            raise ValueError(f"experiment config references unset env var ${{{var}}} (no default)")

        return _ENV_PATTERN.sub(_repl, obj)
    if isinstance(obj, dict):
        return {k: _interpolate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(x) for x in obj]
    return obj


def _resolve_cases(spec: Any, materials_root: Path) -> list[Case]:
    if isinstance(spec, str):
        raw = yaml.safe_load((materials_root / "cases" / spec).read_text(encoding="utf-8")) or {}
        items = raw["cases"] if isinstance(raw, dict) else raw
    elif isinstance(spec, list):
        items = spec
    else:
        raise ValueError("evalset.cases must be a filename or an inline list")
    return [case_from_raw(c) for c in items]


def _source(s: dict, base: Path) -> SourceRecord:
    """Resolve a source's ``uri`` to an absolute path (relative to the evalset file's dir);
    URLs and inline content pass through unchanged."""
    uri = s.get("uri")
    if uri and "://" not in uri and not Path(uri).is_absolute():
        uri = str((base / uri).resolve())
    return SourceRecord(
        name=s["name"],
        uri=uri,
        content=s.get("content"),
        selected=bool(s.get("selected", True)),
        meta=dict(s.get("meta") or {}),
    )


def _load_evalset(spec: Any, root: Path) -> EvalSet:
    """An evalsets entry is either a path to a unified ``evalset.yaml`` (corpus + sources +
    cases) or an inline mapping. Source uris resolve relative to the evalset file's dir
    (inline: relative to materials root)."""
    if isinstance(spec, str):
        es_path = Path(spec) if Path(spec).is_absolute() else (root / spec)
        raw = _interpolate(yaml.safe_load(es_path.read_text(encoding="utf-8")) or {})
        base = es_path.parent
    elif isinstance(spec, dict):
        raw, base = spec, root
    else:
        raise ValueError("evalsets entry must be a path or an inline mapping")
    return EvalSet(
        corpus=raw["corpus"],
        sources=[_source(s, base) for s in (raw.get("sources") or [])],
        cases=_resolve_cases(raw["cases"], root),
        focus=raw.get("focus"),
        domain=raw.get("domain"),
    )


def load_experiment(path: str | Path, materials_root: str | Path | None = None) -> Experiment:
    path = Path(path)
    raw = _interpolate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    # experiments/<x>.yaml lives under materials/, so materials root = parent of experiments/
    root = Path(materials_root) if materials_root else path.parents[1]

    # evalsets: a list of {corpus, cases}; `evalset` (singular) is single-corpus sugar.
    raw_evalsets = raw.get("evalsets") or ([raw["evalset"]] if "evalset" in raw else [])
    if not raw_evalsets:
        raise ValueError("experiment config needs `evalset` or `evalsets`")
    evalsets = [_load_evalset(e, root) for e in raw_evalsets]
    facets = {k: FacetSpec(**(v or {})) for k, v in (raw.get("facets") or {}).items()}

    exp = Experiment(
        name=raw["name"],
        description=raw.get("description") or "",
        target=Target(**raw["target"]),
        evalsets=evalsets,
        facets=facets,
        envs=[Env(**e) for e in (raw.get("envs") or [])],
        matrix=raw.get("matrix") or {},
        metrics=raw.get("metrics") or [],
        weights=raw.get("weights") or {},
        heavy_fields=raw.get("heavy_fields") or [],
    )
    schema = exp.facet_schema()
    for es in exp.evalsets:
        es.validate_against(schema)  # fail loud on bad facet values
    return exp

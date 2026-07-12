"""Metric layer: fills the metric columns of the Worksheet.

A metric reads one ``Sample`` and returns a ``MetricResult`` (quality or
measurement). It never knows about Env / Experiment / the Worksheet — the
table is the contract between this layer and the report layer.

- ``base`` — ``BaseMetric`` (NAME / KIND / WEIGHT / applies_to / score).
- ``aggregate`` — ``weighted_overall`` + measurement percentiles (pure).
"""

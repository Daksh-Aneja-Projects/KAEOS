"""Observability config sanity - alerts and dashboards reference real metrics.

Guards prometheus/alerts.yml and the provisioned Grafana dashboard against the
classic silent failure: a rule or panel pointing at a metric name nothing
exports, which never fires and never errors. Allowlist = the kaeos_* families
declared in app/core/metrics.py plus the instrumentator/Prometheus standards
(http_*, process_*, up). Unit-lane only: file parsing, no services.
"""
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
METRICS_SRC = (REPO / "backend" / "app" / "core" / "metrics.py").read_text(encoding="utf-8")

# Families not declared in metrics.py: prometheus-fastapi-instrumentator
# defaults plus the Prometheus-synthesized `up`.
STANDARD_FAMILIES = {
    "http_requests_total",
    "http_request_duration_seconds",
    "http_request_duration_highr_seconds",
    "http_request_size_bytes",
    "http_response_size_bytes",
    "up",
}

METRIC_TOKEN = re.compile(r"\b(kaeos_[a-z0-9_]+|http_[a-z0-9_]+|process_[a-z0-9_]+|up)\b")


def _base(name: str) -> str:
    """Strip histogram sample suffixes down to the declared family name."""
    return re.sub(r"_(bucket|sum|count)$", "", name)


def _family_ok(base: str) -> bool:
    return (
        base in STANDARD_FAMILIES
        or base.startswith("process_")  # prometheus_client process collector
        or f'"{base}"' in METRICS_SRC
    )


def test_alert_exprs_reference_only_real_metric_families():
    doc = yaml.safe_load((REPO / "prometheus" / "alerts.yml").read_text(encoding="utf-8"))
    rules = [r for g in doc["groups"] for r in g["rules"]]
    assert rules, "alerts.yml has no rules"
    for rule in rules:
        tokens = METRIC_TOKEN.findall(rule["expr"])
        assert tokens, f"{rule['alert']}: no recognizable metric name in expr"
        for tok in tokens:
            assert _family_ok(_base(tok)), (
                f"{rule['alert']}: metric {_base(tok)} is not exported by "
                "app/core/metrics.py or the standard http_/process_/up families"
            )


def test_observability_yaml_files_parse():
    for rel in (
        "prometheus.yml",
        "prometheus/alerts.yml",
        "alertmanager.yml",
        "docker-compose.yml",
        "grafana/provisioning/datasources/prometheus.yml",
        "grafana/provisioning/dashboards/provider.yml",
    ):
        assert yaml.safe_load((REPO / rel).read_text(encoding="utf-8")), rel


def test_grafana_dashboard_parses_and_uses_real_metrics():
    dash = json.loads(
        (REPO / "grafana" / "provisioning" / "dashboards" / "kaeos.json").read_text(encoding="utf-8")
    )
    exprs = [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    assert exprs, "dashboard has no query targets"
    for expr in exprs:
        for tok in METRIC_TOKEN.findall(expr):
            assert _family_ok(_base(tok)), f"dashboard metric {_base(tok)} not exported"

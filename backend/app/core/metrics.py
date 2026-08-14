"""KAEOS - Prometheus golden-signal metrics.

Domain metrics for the parts of the system the HTTP instrumentator cannot see:
the gate pipeline, LLM calls, the durable job queue, HITL, and leader election.
The HTTP golden signals (request rate/latency/in-progress) come from
prometheus-fastapi-instrumentator in main.py; these are the governance-specific
counters an operator actually pages on.

Multiprocess safety: under ``gunicorn -w4`` every worker is a separate process
with its own registry. When ``PROMETHEUS_MULTIPROC_DIR`` is set (see
gunicorn.conf.py) prometheus_client writes each metric to a shared mmap file and
the /metrics endpoint aggregates across workers via MultiProcessCollector.
Counters/Histograms do this transparently; a Gauge must declare how to combine
per-process values, hence ``multiprocess_mode`` on LEADER below.

Every call site wraps these in try/except: a metrics hiccup must never break a
governed decision. This module never raises on import.
"""
from prometheus_client import Counter, Histogram, Gauge

# ── Gate pipeline (the product's core loop) ──────────────────────────────────
# Every gate transition routes through AgentExecutor._emit_gate, so this counter
# is a complete census of what the pipeline did: which gate, which verdict.
GATE_TRANSITIONS = Counter(
    "kaeos_gate_transitions_total",
    "Gate pipeline transitions by gate and resolved state.",
    ["gate", "state"],
)
# Terminal outcome + wall time of a full execute_skill() run.
PIPELINE_RESULTS = Counter(
    "kaeos_gate_pipeline_total",
    "Gate pipeline terminal outcomes by status.",
    ["status"],
)
PIPELINE_LATENCY = Histogram(
    "kaeos_gate_pipeline_seconds",
    "Full gate pipeline wall time (seconds), by terminal status.",
    ["status"],
)

# ── LLM calls ────────────────────────────────────────────────────────────────
# Metered once per real completion in LLMRouter._record_cost (the single point
# every model call funnels through for billing).
LLM_CALLS = Counter(
    "kaeos_llm_calls_total",
    "Completed LLM model calls by tier.",
    ["tier"],
)
LLM_LATENCY = Histogram(
    "kaeos_llm_latency_seconds",
    "LLM call latency (seconds) by tier.",
    ["tier"],
)

# ── Durable job queue ────────────────────────────────────────────────────────
JOBS_PROCESSED = Counter(
    "kaeos_jobs_total",
    "Durable-queue jobs processed by outcome (succeeded/failed/retried).",
    ["outcome"],
)

# ── HITL ─────────────────────────────────────────────────────────────────────
HITL_REQUESTS = Counter(
    "kaeos_hitl_requests_total",
    "Human-in-the-loop pauses requested.",
)
HITL_RESOLUTIONS = Counter(
    "kaeos_hitl_resolutions_total",
    "Human-in-the-loop resolutions by decision (approved/rejected).",
    ["decision"],
)

# ── Leader election ──────────────────────────────────────────────────────────
# 1 on the process that currently holds background-job leadership, else 0.
# livesum: summed across live workers, so a healthy cluster reads exactly 1 and
# a split-brain (two leaders) reads 2 - which is precisely the alert condition.
LEADER = Gauge(
    "kaeos_background_leader",
    "1 if this process holds background-job leadership, else 0.",
    multiprocess_mode="livesum",
)


def observe_pipeline(status: str, total_ms: int) -> None:
    """Record a completed gate-pipeline run. Never raises."""
    try:
        s = str(status)
        PIPELINE_RESULTS.labels(status=s).inc()
        PIPELINE_LATENCY.labels(status=s).observe(total_ms / 1000.0)
    except Exception:
        pass


if __name__ == "__main__":
    # Self-check: metrics are defined, labelled, and increment without raising.
    GATE_TRANSITIONS.labels(gate="compliance", state="passed").inc()
    observe_pipeline("SUCCESS_CLEAN", 1234)
    LLM_CALLS.labels(tier="reasoning").inc()
    JOBS_PROCESSED.labels(outcome="succeeded").inc(3)
    HITL_REQUESTS.inc()
    HITL_RESOLUTIONS.labels(decision="approved").inc()
    LEADER.set(1)
    from prometheus_client import generate_latest
    dump = generate_latest().decode()
    assert "kaeos_gate_transitions_total" in dump
    assert "kaeos_gate_pipeline_seconds" in dump
    assert "kaeos_background_leader" in dump
    print("metrics self-check OK")

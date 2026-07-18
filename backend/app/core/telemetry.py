import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

def setup_telemetry():
    """Configure OpenTelemetry tracing for FastAPI and agent loops.

    Export target:
      - OTEL_EXPORTER_OTLP_ENDPOINT set → OTLP (Jaeger/Datadog/Tempo/etc.)
      - DEBUG=true → console (dev verification)
      - otherwise → spans are collected but not exported (no per-request
        JSON blobs spamming production stdout)
    """
    import os
    try:
        provider = TracerProvider()

        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                logger.info("[Observability] OTLP span exporter configured.")
            except ImportError:
                logger.warning(
                    "[Observability] OTEL_EXPORTER_OTLP_ENDPOINT set but "
                    "opentelemetry-exporter-otlp is not installed — traces not exported."
                )
        else:
            from app.core.config import get_settings
            if get_settings().DEBUG:
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
                logger.info("[Observability] Console span exporter configured (DEBUG).")

        trace.set_tracer_provider(provider)
        logger.info("[Observability] OpenTelemetry provider configured.")
        return provider
    except Exception as e:
        logger.warning(f"[Observability] Failed to configure OpenTelemetry: {e}")
        return None

# Global tracer instance for agent loops
tracer = trace.get_tracer("kaeos.agents")

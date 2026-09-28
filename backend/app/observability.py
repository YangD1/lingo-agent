"""Optional OpenTelemetry tracing for LangChain / LangGraph (ADR 0005).

Disabled by default. When enabled, OpenInference hooks LangChain's callback system
(it wraps `BaseCallbackManager.__init__`), so every Runnable - LangGraph nodes and
model calls included - becomes an OTel span exported over OTLP/HTTP to whatever
backend the deployer configured (local Phoenix in dev).
"""

import logging

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.settings import Settings

logger = logging.getLogger(__name__)


def setup_tracing(
    settings: Settings, span_processor: SpanProcessor | None = None
) -> TracerProvider | None:
    """Instrument LangChain if tracing is enabled; returns the provider to shut down later.

    `span_processor` overrides the OTLP exporter (tests pass an in-memory one).
    """
    if not settings.otel_tracing_enabled:
        logger.info("OTel tracing disabled")
        return None

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    if span_processor is None:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        span_processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(span_processor)
    # Passing the provider explicitly avoids mutating the global OTel tracer provider.
    LangChainInstrumentor().instrument(tracer_provider=provider)
    logger.info("OTel tracing enabled, exporting to %s", settings.otel_exporter_otlp_endpoint)
    return provider


def shutdown_tracing(provider: TracerProvider | None) -> None:
    """Flush pending spans and remove the LangChain instrumentation."""
    if provider is None:
        return
    LangChainInstrumentor().uninstrument()
    provider.shutdown()

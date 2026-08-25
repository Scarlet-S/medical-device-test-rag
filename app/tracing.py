import os
from contextlib import contextmanager
from typing import Any, Iterator


_OTEL_AVAILABLE = False
_CONFIGURED = False

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    _OTEL_AVAILABLE = True
except ImportError:
    trace = None


def tracing_enabled() -> bool:
    return os.getenv("OTEL_TRACES_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configure_tracing(app: Any | None = None) -> bool:
    """Configure OTLP export once; telemetry failures never break the API."""
    global _CONFIGURED
    if _CONFIGURED or not _OTEL_AVAILABLE or not tracing_enabled():
        return _CONFIGURED

    try:
        sample_ratio = min(
            1.0,
            max(0.0, float(os.getenv("OTEL_TRACE_SAMPLE_RATIO", "1.0"))),
        )
        resource = Resource.create(
            {
                "service.name": os.getenv(
                    "OTEL_SERVICE_NAME",
                    "medical-device-agent-api",
                ),
                "service.version": "1.3.0",
                "deployment.environment": os.getenv(
                    "DEPLOYMENT_ENVIRONMENT",
                    "local",
                ),
            }
        )
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
        )
        exporter = OTLPSpanExporter(
            endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "http://localhost:4318/v1/traces",
            )
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        RequestsInstrumentor().instrument()
        RedisInstrumentor().instrument()
        if app is not None:
            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="health,metrics",
            )
        _CONFIGURED = True
    except Exception:
        return False
    return True


def get_trace_ids() -> tuple[str, str]:
    if not _OTEL_AVAILABLE:
        return "", ""
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return "", ""
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


@contextmanager
def traced_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    if not _OTEL_AVAILABLE or not tracing_enabled():
        yield None
        return

    tracer = trace.get_tracer("medical_device_rag")
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise

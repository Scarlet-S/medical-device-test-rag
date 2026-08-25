import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from prometheus_client import Counter, Histogram

from app.tracing import get_trace_ids


HTTP_REQUESTS = Counter(
    "mdtr_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "mdtr_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "route"),
)
RAGFLOW_CALLS = Counter(
    "mdtr_ragflow_calls_total",
    "RAGFlow question calls by outcome.",
    ("status",),
)
RAGFLOW_DURATION = Histogram(
    "mdtr_ragflow_call_duration_seconds",
    "RAGFlow question call latency in seconds.",
)
AGENT_ROUTES = Counter(
    "mdtr_agent_routes_total",
    "Intent router selections.",
    ("agent",),
)
ROUTER_CONFIDENCE = Histogram(
    "mdtr_router_confidence",
    "Intent-router confidence by selected agent.",
    ("agent",),
    buckets=(0.0, 0.4, 0.55, 0.7, 0.85, 0.95, 1.0),
)
AGENT_EXECUTIONS = Counter(
    "mdtr_agent_executions_total",
    "Specialist and workflow agent executions by outcome.",
    ("agent", "status"),
)
AGENT_DURATION = Histogram(
    "mdtr_agent_duration_seconds",
    "Agent execution latency in seconds.",
    ("agent",),
)
TOOL_CALLS = Counter(
    "mdtr_tool_calls_total",
    "Agent tool calls by tool and outcome.",
    ("tool", "status"),
)
TOOL_DURATION = Histogram(
    "mdtr_tool_duration_seconds",
    "Agent tool-call latency in seconds.",
    ("tool",),
)
AGENT_ESTIMATED_TOKENS = Counter(
    "mdtr_agent_estimated_tokens_total",
    "Heuristic token estimate by agent and direction.",
    ("agent", "direction"),
)
AGENT_ESTIMATED_COST_USD = Counter(
    "mdtr_agent_estimated_cost_usd_total",
    "Estimated model cost in USD when pricing is configured.",
    ("agent",),
)
EVALUATION_JOBS = Counter(
    "mdtr_evaluation_jobs_total",
    "Evaluation jobs by terminal or accepted state.",
    ("status",),
)
MEMORY_OPERATIONS = Counter(
    "mdtr_memory_operations_total",
    "Redis conversation-memory operations.",
    ("operation", "status"),
)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line without logging request content."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = get_trace_ids()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        for field in (
            "request_id",
            "method",
            "route",
            "status_code",
            "elapsed_ms",
            "agent",
            "job_id",
            "event",
            "status",
            "tool",
            "estimated_cost_usd",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("medical_device_rag")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


LOGGER = configure_logging()

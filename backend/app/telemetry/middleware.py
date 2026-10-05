"""FastAPI OpenTelemetry Tracing Middleware (Roadmap Initiative C).

Extracts inbound W3C traceparent headers, attaches spans to incoming requests,
and injects traceparent and X-Trace-Id into all outgoing HTTP responses.
"""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.telemetry.tracer import (
    extract_trace_context,
    get_current_trace_id,
    get_tracer,
    inject_trace_context,
    start_trace_span,
)


class OpenTelemetryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service_name: str = "flowsmith-api") -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract incoming W3C traceparent context from request headers
        headers_dict = dict(request.headers)
        parent_context = extract_trace_context(headers_dict)

        span_name = f"HTTP {request.method} {request.url.path}"
        attributes = {
            "http.method": request.method,
            "http.url": str(request.url),
            "http.target": request.url.path,
            "http.client_ip": request.client.host if request.client else "unknown",
            "service.name": self.service_name,
        }

        with start_trace_span(span_name, attributes=attributes, parent_context=parent_context) as span:
            start_time = time.perf_counter()
            response: Response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            span.set_attribute("http.status_code", response.status_code)
            span.set_attribute("http.duration_ms", elapsed_ms)

            # Inject trace headers into response
            trace_id = get_current_trace_id()
            if trace_id:
                response.headers["X-Trace-Id"] = trace_id
                inject_headers: dict[str, str] = {}
                inject_trace_context(inject_headers)
                if "traceparent" in inject_headers:
                    response.headers["traceparent"] = inject_headers["traceparent"]

            return response

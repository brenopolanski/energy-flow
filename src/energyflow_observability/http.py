"""HTTP request ids, access logs, and the /metrics response."""

import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from fastapi import FastAPI
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from energyflow_observability.context import request_id_var
from energyflow_observability.logging import configure_logging
from energyflow_observability.metrics import HTTP_LATENCY, HTTP_REQUESTS, render_metrics

logger = logging.getLogger(__name__)

_SKIPPED_PATHS = {"/health", "/metrics"}


def route_label(path: str) -> str:
    """Collapse ids so a metric label does not grow with every reading."""
    if path.startswith("/results/"):
        return "/results/{reading_id}"
    return path


class ObservabilityMiddleware:
    """Copy or create X-Request-ID and record the call."""

    def __init__(self, app: ASGIApp, service: str) -> None:
        self.app = app
        self._service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        incoming = headers.get("x-request-id", "").strip()
        request_id = incoming or str(uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        path = route_label(scope.get("path", ""))
        method = scope.get("method", "")

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                raw = list(message.get("headers") or [])
                raw.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            request_id_var.reset(token)
            if path not in _SKIPPED_PATHS:
                HTTP_REQUESTS.labels(
                    self._service,
                    method,
                    path,
                    str(status_code),
                ).inc()
                HTTP_LATENCY.labels(self._service, method, path).observe(elapsed)
                logger.info(
                    "request",
                    extra={
                        "request_id": request_id,
                        "method": method,
                        "path": path,
                        "status": status_code,
                        "duration_seconds": round(elapsed, 6),
                    },
                )


def install_observability(app: FastAPI, service: str) -> None:
    """Turn on JSON logs, the request middleware, and /metrics."""
    configure_logging(service)
    app.add_middleware(ObservabilityMiddleware, service=service)

    def metrics() -> Response:
        return Response(
            content=render_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.add_api_route("/metrics", metrics, methods=["GET"], include_in_schema=False)


def serve_worker_endpoints(port: int | None = None) -> None:
    """Serve /health and /metrics from the Celery worker process."""
    selected = port if port is not None else int(os.environ.get("ENERGYFLOW_METRICS_PORT", "9100"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                body = b'{"status":"ok"}'
                content_type = "application/json"
                status = 200
            elif path == "/metrics":
                body = render_metrics()
                content_type = "text/plain; version=0.0.4; charset=utf-8"
                status = 200
            else:
                body = b""
                content_type = "text/plain"
                status = 404
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", selected), Handler)
    thread = threading.Thread(target=server.serve_forever, name="energyflow-metrics", daemon=True)
    thread.start()
    logger.info("worker endpoints listening", extra={"path": f":{selected}"})

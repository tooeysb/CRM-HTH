"""
Correlation ID middleware for request tracing.

Assigns a unique request_id to every incoming request and makes it available
via a contextvars.ContextVar so that log formatters can include it automatically.
"""

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Context variable holding the current request's correlation ID.
# Accessible from any code running in the same async context (routes, services, etc.).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject a correlation ID into every request and expose it in the response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use client-supplied header if present, otherwise generate one.
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        token = request_id_var.set(rid)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)

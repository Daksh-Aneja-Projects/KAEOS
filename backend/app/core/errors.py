"""Application-wide handling for genuinely-uncaught exceptions.

FastAPI has no catch-all beyond returning a bare 500 whose body, under some
server configs, carries the exception string — which leaks internal detail
(file paths, SQL fragments, stack context) to the caller. This installs one
handler that logs the full traceback server-side and returns a stable,
non-leaky envelope carrying the request id, so support can correlate a user's
500 with the server log without the user ever seeing internals.

Scope is deliberate. `HTTPException` (the 4xx/5xx a handler raises on purpose)
and `RequestValidationError` keep FastAPI's existing ``{"detail": ...}``
contract, which the frontend error parser and the e2e suite already depend on.
Only exceptions that reach the server with no handler of their own are reshaped.
"""
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception on %s %s (req=%s)",
        request.method, request.url.path, request_id,
    )
    body = {
        "error": {
            "code": "internal_error",
            "message": (
                "An internal error occurred. Quote the request id to support "
                "if it persists."
            ),
            "request_id": request_id,
        }
    }
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(status_code=500, content=body, headers=headers)


def install_error_handlers(app) -> None:
    """Register the catch-all. Call once, after the FastAPI app is created."""
    app.add_exception_handler(Exception, unhandled_exception_handler)


def _demo() -> None:
    """Self-check: an uncaught error yields the envelope and hides internals."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise ValueError("secret internal path /var/db/passwd")

    # raise_server_exceptions=False so TestClient returns the handler's response
    # instead of re-raising, mirroring real ASGI behaviour.
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500, r.status_code
    payload = r.json()
    assert payload["error"]["code"] == "internal_error", payload
    assert "secret internal path" not in r.text, "internals leaked to client"
    print("errors._demo OK")


if __name__ == "__main__":
    _demo()

"""MCP Streamable HTTP transport (single `/mcp` endpoint) with the spec's transport-level security rules.

POST   /mcp  JSON-RPC request(s); replies with application/json, or text/event-stream when the client accepts it
             and the call reports progress (run_analysis).
GET    /mcp  405 - this server never opens a server-initiated stream (allowed by the spec).
DELETE /mcp  terminate the session named by Mcp-Session-Id.
"""

import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import Settings
from app.mcp.governance import Principal
from app.mcp.server import (
    DEFAULT_VERSION,
    INVALID_REQUEST,
    PARSE_ERROR,
    SUPPORTED_VERSIONS,
    Conn,
    MCPRuntime,
    _err,
)
from app.mcp.store import AuditEntry
from app.mcp.tools import build_registry

log = logging.getLogger(__name__)
MAX_BODY_BYTES = 256 * 1024


def _runtime(request: Request) -> MCPRuntime | None:
    state = request.app.state
    container = getattr(state, "container", None)
    if container is None:
        return None
    runtime = getattr(state, "mcp_runtime", None)
    if runtime is None or runtime.container is not container:
        runtime = state.mcp_runtime = MCPRuntime(container, build_registry())
    return runtime


def _origin_allowed(origin: str, request: Request, settings: Settings) -> bool:
    if origin in settings.mcp_allowed_origins:
        return True
    host = urlparse(origin).netloc
    return bool(host) and host == request.headers.get("host")  # same-origin


async def _audit_gate(runtime: MCPRuntime, request: Request, outcome: str, detail: str) -> None:
    entry = AuditEntry(None, "unknown", "none", "http", "http/request", request.url.path, None, outcome, detail, 0)
    try:
        await asyncio.to_thread(runtime.audit.record, entry)
    except Exception:  # pragma: no cover - refusal already being returned
        log.error("audit write failed for %s", outcome)


def create_mcp_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/mcp")
    async def mcp_post(request: Request):
        runtime = _runtime(request)
        if runtime is None:
            return JSONResponse(_err(None, -32603, "TRACE is not ready (dataset missing); see /api/health"), 503)

        origin = request.headers.get("origin")
        if origin and not _origin_allowed(origin, request, settings):
            await _audit_gate(runtime, request, "denied", f"origin {origin[:80]}")
            return JSONResponse(_err(None, INVALID_REQUEST, "Origin not allowed"), 403)

        principal: Principal | None = runtime.auth.authenticate(request.headers.get("authorization"))
        if principal is None:
            await _audit_gate(runtime, request, "unauthenticated", "missing or invalid bearer token")
            return JSONResponse(
                _err(None, INVALID_REQUEST, "Authentication required"), 401, headers={"WWW-Authenticate": "Bearer"}
            )

        version = request.headers.get("mcp-protocol-version")
        if version and version not in SUPPORTED_VERSIONS:
            return JSONResponse(
                _err(None, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version {version}; use one of {SUPPORTED_VERSIONS}"),
                400,
            )

        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(_err(None, INVALID_REQUEST, "Request too large"), 413)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(_err(None, PARSE_ERROR, "Parse error"), 400)

        first = payload[0] if isinstance(payload, list) and payload else payload
        is_init = isinstance(first, dict) and first.get("method") == "initialize"
        conn = Conn(principal=principal, transport="http")
        session_id = request.headers.get("mcp-session-id")
        if not is_init:
            if not session_id:
                return JSONResponse(_err(None, INVALID_REQUEST, "Mcp-Session-Id header required"), 400)
            session = runtime.sessions.get(session_id)
            if session is None:
                return JSONResponse(_err(None, INVALID_REQUEST, "Unknown or expired session"), 404)
            if session.principal != principal.name:  # a stolen session id is useless to a different identity
                await _audit_gate(runtime, request, "denied", "session/principal mismatch")
                return JSONResponse(_err(None, INVALID_REQUEST, "Session does not belong to this principal"), 403)
            conn.session = session

        wants_sse = "text/event-stream" in request.headers.get("accept", "") and _reports_progress(payload)
        if wants_sse:
            return _sse(runtime, payload, conn)

        response = await runtime.handle_payload(payload, conn)
        headers = {"Mcp-Session-Id": conn.session.id} if is_init and conn.session else {}
        if response is None:
            return Response(status_code=202, headers=headers)
        return JSONResponse(response, headers=headers)

    @router.get("/mcp")
    async def mcp_get():
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})

    @router.delete("/mcp")
    async def mcp_delete(request: Request):
        runtime = _runtime(request)
        if runtime is None:
            return Response(status_code=503)
        principal = runtime.auth.authenticate(request.headers.get("authorization"))
        if principal is None:
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        session = runtime.sessions.get(request.headers.get("mcp-session-id"))
        if session is None:
            return Response(status_code=404)
        if session.principal != principal.name:
            return Response(status_code=403)
        runtime.sessions.end(session.id)
        return Response(status_code=204)

    return router


def _reports_progress(payload) -> bool:
    msgs = payload if isinstance(payload, list) else [payload]
    for m in msgs:
        params = m.get("params") if isinstance(m, dict) else None
        meta = params.get("_meta") if isinstance(params, dict) else None
        if isinstance(meta, dict) and meta.get("progressToken") is not None:
            return True
    return False


def _sse(runtime: MCPRuntime, payload, conn: Conn) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()

    async def notify(message: dict) -> None:
        await queue.put(message)

    conn.notify = notify

    async def work() -> None:
        try:
            response = await runtime.handle_payload(payload, conn)
            if response is not None:
                await queue.put(response)
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(work())
        try:
            while (message := await queue.get()) is not None:
                yield f"event: message\ndata: {json.dumps(message, default=str)}\n\n"
        finally:
            if not task.done():  # client went away: stop the work
                task.cancel()

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

"""System-test API. The run executes inside the streaming request: closing the stream cancels the run.

That keeps it correct on Cloud Run, where CPU is only guaranteed while a request is open and in-memory state is
per instance.
"""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.mcp.governance import Authenticator, Principal
from app.testing.harness import PROFILES, Runner
from app.testing.suites import build_cases

router = APIRouter(prefix="/api/system-tests")
HEARTBEAT_S = 15


def _authorize(request: Request) -> Principal:
    c = getattr(request.app.state, "container", None)
    if c is None:
        raise HTTPException(503, "Service is starting")
    runtime = getattr(request.app.state, "mcp_runtime", None)
    auth = runtime.auth if runtime is not None else Authenticator(c.settings.mcp_api_keys)
    principal = auth.authenticate(request.headers.get("authorization"))
    if principal is None:
        raise HTTPException(401, "An analyst API key is required", headers={"WWW-Authenticate": "Bearer"})
    if not principal.allows("analyst"):
        raise HTTPException(403, "Running system tests requires the analyst role or higher")
    if principal.name.startswith("system-test-"):
        raise HTTPException(403, "System-test principals cannot start runs")
    return principal


@router.get("/plan")
def plan(profile: Literal["full", "quick"] = "full") -> dict:
    p = PROFILES[profile]
    cases = build_cases(p)
    return {"profile": profile, "target_s": p.target_s, "tests": [c.plan() for c in cases],
            "suites": list(dict.fromkeys(c.suite for c in cases))}  # fmt: skip


@router.get("/last")
def last(request: Request) -> dict:
    _authorize(request)
    if Runner.last_report is None:
        raise HTTPException(404, "No completed run on this instance")
    return Runner.last_report


@router.post("/run")
async def run(request: Request, profile: Literal["full", "quick"] = Query("full")) -> StreamingResponse:
    principal = _authorize(request)
    if Runner.lock.locked():
        raise HTTPException(409, "A system-test run is already in progress")
    await Runner.lock.acquire()
    runner = Runner(request.app, request.app.state.container, PROFILES[profile], build_cases(PROFILES[profile]))

    async def events():
        task = asyncio.create_task(runner.run())
        try:
            yield _sse("hello", {"run_id": runner.run_id, "started_by": principal.name})
            while True:
                try:
                    event = await asyncio.wait_for(runner.queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    yield ": heartbeat\n\n"  # keeps proxies from closing a quiet stream
                    continue
                yield _sse(event["type"], event)
                if event["type"] == "run_finished":
                    break
            await task
        except Exception as exc:  # surface harness crashes to the client instead of a dropped stream
            yield _sse("run_error", {"type": "run_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            if not task.done():  # client went away: stop testing
                task.cancel()
            Runner.lock.release()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"

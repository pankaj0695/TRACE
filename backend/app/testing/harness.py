"""In-process system-test harness: runs real checks against the live application and streams results.

Nothing here is simulated: HTTP checks go through the full ASGI stack (middleware included), MCP checks open real
sessions, pipeline checks run the real agents and LLM. Failures are whatever the system actually does.
"""

import asyncio
import logging
import secrets
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.mcp.governance import Principal

log = logging.getLogger(__name__)

Kind = Literal["positive", "negative", "resilience", "load"]
Status = Literal["passed", "failed", "error", "skipped"]
PROTOCOL = "2025-06-18"


class Fail(AssertionError):
    def __init__(self, message: str, **evidence: Any):
        super().__init__(message)
        self.evidence = evidence


class Skip(Exception):
    pass


def check(condition: Any, message: str, **evidence: Any) -> None:
    if not condition:
        raise Fail(message, **evidence)


@dataclass
class Case:
    id: str
    suite: str
    name: str
    kind: Kind
    fn: Callable[["TestContext"], Awaitable[dict | None]]
    est_s: float = 1.0
    timeout_s: float = 60.0
    description: str = ""

    def plan(self) -> dict:
        return {"id": self.id, "suite": self.suite, "name": self.name, "kind": self.kind, "est_s": self.est_s,
                "description": self.description}  # fmt: skip


@dataclass
class Profile:
    name: str
    target_s: float  # the run aims to finish near this; the soak absorbs the slack
    pipeline_listings: int
    perf_window_s: float
    soak_min_s: float
    soak_max_s: float
    soak_workers: int


PROFILES = {
    "full": Profile("full", target_s=780, pipeline_listings=5, perf_window_s=120, soak_min_s=90, soak_max_s=480, soak_workers=8),
    "quick": Profile("quick", target_s=150, pipeline_listings=2, perf_window_s=20, soak_min_s=20, soak_max_s=40, soak_workers=4),
}


@dataclass
class TestContext:
    app: Any
    container: Any
    profile: Profile
    started: float
    emit: Callable[[dict], Awaitable[None]]
    http: httpx.AsyncClient = None  # type: ignore[assignment]
    shared: dict = field(default_factory=dict)
    tokens: dict[str, str] = field(default_factory=dict)  # role-label -> ephemeral token
    run_id: str = ""

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self) -> float:
        return self.profile.target_s - self.elapsed

    async def log(self, msg: str, level: str = "info") -> None:
        await self.emit({"type": "log", "level": level, "msg": msg, "t": round(self.elapsed, 2)})

    # -- MCP helpers ---------------------------------------------------------------------------------------------

    def runtime(self):
        return getattr(self.app.state, "mcp_runtime", None)

    def headers(self, token: str | None, session: str | None = None, **extra) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json", "MCP-Protocol-Version": PROTOCOL}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if session:
            h["Mcp-Session-Id"] = session
        return h | extra

    async def mcp_session(self, token: str) -> str:
        r = await self.http.post("/mcp", headers=self.headers(token), json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "trace-system-tests", "version": "1"}},
        })  # fmt: skip
        check(r.status_code == 200, f"initialize returned {r.status_code}", body=r.text[:300])
        sid = r.headers.get("mcp-session-id")
        check(sid, "initialize did not return an Mcp-Session-Id")
        await self.http.post("/mcp", headers=self.headers(token, sid), json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        return sid

    async def mcp(self, token: str, sid: str, method: str, params: dict | None = None) -> httpx.Response:
        body = {"jsonrpc": "2.0", "id": secrets.randbelow(10**6), "method": method, "params": params or {}}
        return await self.http.post("/mcp", headers=self.headers(token, sid), json=body)

    async def tool(self, token: str, sid: str, name: str, args: dict | None = None) -> dict:
        r = await self.mcp(token, sid, "tools/call", {"name": name, "arguments": args or {}})
        check(r.status_code == 200, f"tools/call {name} HTTP {r.status_code}", body=r.text[:300])
        return r.json()


def _ensure_mcp_runtime(app) -> Any:
    """The MCP runtime is created lazily by the first /mcp request; create it the same way if needed."""
    from app.mcp.http import _runtime

    class _Req:  # minimal shim: _runtime only touches request.app.state
        def __init__(self, a):
            self.app = a

    return _runtime(_Req(app))


class Runner:
    """Executes the plan sequentially and streams events. One run per process at a time."""

    lock = asyncio.Lock()
    last_report: dict | None = None

    def __init__(self, app, container, profile: Profile, cases: list[Case]):
        self.app, self.container, self.profile, self.cases = app, container, profile, cases
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results: list[dict] = []
        self.run_id = secrets.token_hex(4)

    async def emit(self, event: dict) -> None:
        await self.queue.put(event)

    async def run(self) -> dict:
        started = time.monotonic()
        ctx = TestContext(self.app, self.container, self.profile, started, self.emit, run_id=self.run_id)
        transport = httpx.ASGITransport(app=self.app)
        runtime = _ensure_mcp_runtime(self.app) if self.container.settings.mcp_enabled else None
        ephemeral = {}
        if runtime is not None:  # throwaway principals: rate-limit/role tests never touch real users' buckets
            for label, role in (("analyst", "analyst"), ("burst", "analyst"), ("viewer", "viewer"), ("admin", "admin")):
                token = secrets.token_urlsafe(32)
                runtime.auth.add_ephemeral(token, Principal(f"system-test-{self.run_id}-{label}", role))
                ephemeral[label] = token
            for i in range(self.profile.soak_workers):
                token = secrets.token_urlsafe(32)
                runtime.auth.add_ephemeral(token, Principal(f"system-test-{self.run_id}-soak{i}", "viewer"))
                ephemeral[f"soak{i}"] = token
        ctx.tokens = ephemeral
        await self.emit({"type": "run_started", "run_id": self.run_id, "profile": self.profile.name,
                         "target_s": self.profile.target_s, "plan": [c.plan() for c in self.cases]})  # fmt: skip
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://trace.internal", timeout=120) as http:
                ctx.http = http
                for case in self.cases:
                    await self._run_case(ctx, case)
        finally:
            if runtime is not None:
                for token in ephemeral.values():
                    runtime.auth.remove_ephemeral(token)
        summary = self._summary(time.monotonic() - started)
        report = {"run_id": self.run_id, "profile": self.profile.name, "summary": summary, "results": self.results,
                  "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}  # fmt: skip
        Runner.last_report = report
        await self.emit({"type": "run_finished", "summary": summary})
        return report

    async def _run_case(self, ctx: TestContext, case: Case) -> None:
        await self.emit({"type": "test_started", "id": case.id, "t": round(ctx.elapsed, 2)})
        t0 = time.monotonic()
        status: Status
        detail, evidence, metrics = "", {}, {}
        try:
            metrics = await asyncio.wait_for(case.fn(ctx), timeout=case.timeout_s) or {}
            status = "passed"
        except Fail as exc:
            status, detail, evidence = "failed", str(exc), exc.evidence
        except Skip as exc:
            status, detail = "skipped", str(exc)
        except TimeoutError:
            status, detail = "error", f"timed out after {case.timeout_s:.0f}s"
        except Exception as exc:  # an unexpected exception is an error, not a failed assertion
            status, detail = "error", f"{type(exc).__name__}: {exc}"
            evidence = {"traceback": traceback.format_exc(limit=4)[-1200:]}
            log.warning("system test %s errored: %s", case.id, exc)
        result = {"id": case.id, "suite": case.suite, "name": case.name, "kind": case.kind, "status": status,
                  "duration_ms": int((time.monotonic() - t0) * 1000), "detail": detail[:1000],
                  "evidence": _jsonable(evidence), "metrics": _jsonable(metrics)}  # fmt: skip
        self.results.append(result)
        await self.emit({"type": "test_finished", **result, "t": round(ctx.elapsed, 2)})

    def _summary(self, duration: float) -> dict:
        counts = {s: sum(r["status"] == s for r in self.results) for s in ("passed", "failed", "error", "skipped")}
        executed = counts["passed"] + counts["failed"] + counts["error"]
        suites: dict[str, dict] = {}
        for r in self.results:
            s = suites.setdefault(r["suite"], {"passed": 0, "failed": 0, "error": 0, "skipped": 0})
            s[r["status"]] += 1
        return {**counts, "total": len(self.results), "pass_rate": round(counts["passed"] / executed, 4) if executed else None,
                "duration_s": round(duration, 1), "suites": suites}  # fmt: skip


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

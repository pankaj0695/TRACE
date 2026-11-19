import json
from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
from app.testing import harness

ANALYST = "analyst-token-0123456789abcdef"
VIEWER = "viewer-token-0123456789abcdef"


def _app(settings):
    return create_app(settings.model_copy(update={"mcp_api_keys": f"{ANALYST}:analyst:ana,{VIEWER}:viewer:vic"}))


def _events(body: str) -> list[dict]:
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def test_plan_is_public_and_lists_suites(settings):
    with TestClient(_app(settings)) as client:
        plan = client.get("/api/system-tests/plan", params={"profile": "quick"}).json()
    assert {"Security", "Governance", "Reliability", "Fault injection"} <= set(plan["suites"])
    assert any(t["kind"] == "negative" for t in plan["tests"])


def test_run_requires_an_analyst_key(settings):
    with TestClient(_app(settings)) as client:
        assert client.post("/api/system-tests/run").status_code == 401
        assert client.post("/api/system-tests/run", headers={"Authorization": f"Bearer {VIEWER}"}).status_code == 403
        assert client.get("/api/system-tests/last", headers={"Authorization": f"Bearer {ANALYST}"}).status_code == 404


def test_quick_run_streams_real_results_and_cleans_up(settings, monkeypatch):
    tiny = replace(harness.PROFILES["quick"], perf_window_s=0.5, soak_min_s=1, soak_max_s=1, soak_workers=2, pipeline_listings=2)
    monkeypatch.setitem(harness.PROFILES, "quick", tiny)
    app = _app(settings)
    with TestClient(app) as client:
        with client.stream("POST", "/api/system-tests/run", params={"profile": "quick"}, headers={"Authorization": f"Bearer {ANALYST}"}) as r:
            events = _events("".join(r.iter_text()))
        types = [e.get("type") for e in events]
        assert types.count("run_started") == 1 and types[-1] == "run_finished"
        finished = [e for e in events if e.get("type") == "test_finished"]
        assert len(finished) == len(events[1]["plan"])
        by_id = {e["id"]: e for e in finished}
        # genuine results: these negative cases must hold on the seeded app
        for case in ("sec.auth", "sec.bad_token", "sec.role", "sec.cors", "sec.session", "sec.rate_limit", "gov.unapproved"):
            assert by_id[case]["status"] == "passed", by_id[case]
        # a known real defect is reported as a failure, not hidden
        assert by_id["gov.redact_dates"]["status"] == "failed"
        # ephemeral principals are removed after the run
        runtime = app.state.mcp_runtime
        assert not any(p.name.startswith("system-test-") for _, p in runtime.auth._keys)
        last = client.get("/api/system-tests/last", headers={"Authorization": f"Bearer {ANALYST}"}).json()
        assert last["summary"]["total"] == len(finished)

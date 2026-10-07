import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agents.orchestrator import OrchestratorAgent
from app.agents.scoring import TrustScoringAgent
from app.container import build_container
from app.domain.models import AgentSignal, RiskTier
from app.llm.client import LLMUnavailable
from app.main import create_app


def run(container, product_id):
    return asyncio.run(container.analysis.run(product_id))


def test_suspicious_listing_outranks_organic_one(settings):
    c = build_container(settings)
    shady, clean = run(c, "SHADY"), run(c, "CLEAN")

    assert shady.assessment.risk_score > clean.assessment.risk_score + 30
    assert shady.assessment.tier in (RiskTier.HIGH, RiskTier.CRITICAL)
    assert clean.assessment.tier == RiskTier.LOW
    codes = {f.code for s in shady.signals.values() for f in s.findings}
    assert {"volume_spike", "near_duplicates", "review_ring"} <= codes


def test_failed_detector_degrades_instead_of_crashing(settings, monkeypatch):
    c = build_container(settings)
    monkeypatch.setattr(c.graph, "neighborhood", lambda pid: (_ for _ in ()).throw(RuntimeError("graph down")))
    analysis = run(c, "SHADY")

    assert analysis.signals["network"].status == "failed"
    assert analysis.assessment.needs_manual_review
    assert "network" not in analysis.assessment.weights
    assert "Partial analysis" in analysis.report.reviewer_note


def test_scoring_flags_conflicting_detectors():
    signals = {
        "anomaly": AgentSignal(agent="anomaly", risk=0.95, confidence=1),
        "authenticity": AgentSignal(agent="authenticity", risk=0.05, confidence=1),
        "network": AgentSignal(agent="network", risk=0.1, confidence=0.9),
    }
    assessment = TrustScoringAgent().assess(signals)
    assert assessment.conflict and assessment.needs_manual_review


def test_scoring_without_usable_signals_is_insufficient():
    assert TrustScoringAgent().assess({}).tier == RiskTier.INSUFFICIENT


class FakeLLM:
    name = "fake-gemini"

    def __init__(self, fail: bool):
        self.fail = fail

    async def generate_json(self, system, prompt, schema):
        if self.fail:
            raise LLMUnavailable("quota")
        return {
            "headline": "LLM headline",
            "summary": "s",
            "findings": [],
            "recommendations": ["r"],
            "reviewer_note": "n",
        }


@pytest.mark.parametrize("fail, expected", [(False, "fake-gemini"), (True, "rules")])
def test_orchestrator_uses_llm_with_rule_fallback(settings, fail, expected):
    c = build_container(settings)
    orchestrator = OrchestratorAgent(FakeLLM(fail), min_reviews=8)
    state = asyncio.run(_state_until_scoring(c, "SHADY"))
    result = asyncio.run(orchestrator(state))
    assert result["report"].generated_by == expected


async def _state_until_scoring(c, product_id):
    state = {"product_id": product_id, "signals": {}}
    async for update in c.analysis.pipeline.astream(state, stream_mode="updates"):
        for node, delta in update.items():
            if node == "orchestrator":
                return state
            state["signals"].update(delta.pop("signals", {}))
            state.update(delta)
    return state


def test_api_streams_stages_and_serves_search(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["graph_backend"] == "networkx"
        assert client.get("/api/products", params={"q": "Aria"}).json()["total"] == 1

        with client.stream("GET", "/api/products/SHADY/analysis/stream") as response:
            body = "".join(response.iter_text())
        assert body.count("event: stage") >= 12 and "event: result" in body

        assert client.get("/api/products/SHADY/analysis").json()["assessment"]["tier"] in ("high", "critical")
        hits = client.get("/api/search/reviews", params={"q": "exceeded expectations"}).json()
        assert hits and hits[0]["product"]["store"] == "Shady Store"
        assert client.get("/api/products/NOPE/analysis/stream").status_code == 404

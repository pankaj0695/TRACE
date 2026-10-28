import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.agents.orchestrator import DETECTORS
from app.data.repositories import AnalysisRepository, ProductRepository, utcnow
from app.domain.models import Analysis, AnalysisSummary, RiskTier
from app.pipeline.graph import STAGES

log = logging.getLogger(__name__)
Event = dict[str, Any]


class AnalysisService:
    """Runs the agent pipeline, streams stage progress and persists the finished analysis."""

    def __init__(
        self,
        pipeline,
        router: Callable[[dict], list[str]],
        products: ProductRepository,
        analyses: AnalysisRepository,
        lineage: Callable[[dict], dict] | None = None,
    ):
        self.lineage = lineage
        self.pipeline = pipeline
        self.router = router
        self.products = products
        self.analyses = analyses
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def stream(self, product_id: str) -> AsyncIterator[Event]:
        async with self._locks[product_id]:
            yield {"event": "started", "stages": STAGES}
            yield {"event": "stage", "stage": "ingestion", "status": "running"}
            state: dict[str, Any] = {"signals": {}}
            try:
                async for update in self.pipeline.astream({"product_id": product_id}, stream_mode="updates"):
                    for node, delta in update.items():
                        state.update({k: v for k, v in delta.items() if k != "signals"})
                        state["signals"].update(delta.get("signals", {}))
                        signal = delta.get("signals", {}).get(node)
                        yield {
                            "event": "stage",
                            "stage": node,
                            "status": signal.status if signal else "ok",
                            "signal": signal.model_dump(mode="json") if signal else None,
                        }
                        for stage in self._unblocked(node, state):
                            yield {"event": "stage", "stage": stage, "status": "running"}
                analysis = self._finalize(state)
                yield {"event": "result", "analysis": analysis.model_dump(mode="json")}
            except LookupError:
                yield {"event": "error", "status": 404, "message": f"Product {product_id} not found"}
            except Exception as exc:
                log.exception("pipeline failed for %s", product_id)
                yield {"event": "error", "status": 500, "message": f"Analysis failed: {exc}"}

    async def run(self, product_id: str) -> Analysis | None:
        async for event in self.stream(product_id):
            if event["event"] == "result":
                return Analysis.model_validate(event["analysis"])
            if event["event"] == "error":
                raise (LookupError if event["status"] == 404 else RuntimeError)(event["message"])
        return None

    def latest(self, product_id: str) -> Analysis | None:
        return self.analyses.get(product_id)

    def summaries(self) -> list[AnalysisSummary]:
        return self.analyses.summaries()

    def _unblocked(self, finished: str, state: dict[str, Any]) -> list[str]:
        """Stages whose inputs are now complete (drives the live 'running' indicators)."""
        if finished == "ingestion":
            return self.router(state)
        if finished in DETECTORS and all(d in state["signals"] for d in DETECTORS):
            return ["scoring"]
        if finished == "scoring":
            return ["orchestrator"]
        return []

    def _finalize(self, state: dict[str, Any]) -> Analysis:
        ctx = state["context"]
        signals = {k: state["signals"][k] for k in STAGES if k in state["signals"]}
        self._attach_titles(signals)
        analysis = Analysis(
            product=ctx.product,
            signals=signals,
            assessment=state["assessment"],
            report=state["report"],
            created_at=utcnow(),
            lineage=self.lineage({**state, "signals": signals}) if self.lineage else {},
        )
        if analysis.assessment.tier != RiskTier.INSUFFICIENT:
            self.analyses.save(analysis)
        return analysis

    def _attach_titles(self, signals) -> None:
        """Give UI-facing artifacts human-readable product titles."""
        network = signals.get("network")
        authenticity = signals.get("authenticity")
        nodes = network.artifacts.get("graph", {}).get("nodes", []) if network else []
        copies = authenticity.artifacts.get("copies", []) if authenticity else []
        ids = [n["id"] for n in nodes if n["kind"] != "reviewer"] + [c["other_product_id"] for c in copies]
        titles = {pid: p.title for pid, p in self.products.get_many(ids).items()}
        for node in nodes:
            if node["kind"] != "reviewer":
                node["title"] = titles.get(node["id"], node["id"])
        for copy in copies:
            copy["other_title"] = titles.get(copy["other_product_id"], copy["other_product_id"])

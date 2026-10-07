import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from time import perf_counter

from app.domain.models import AgentSignal, ProductContext
from app.pipeline.state import PipelineState

log = logging.getLogger(__name__)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def noisy_or(evidence: dict[str, float]) -> float:
    """Combine independent pieces of evidence (each already in [0, 1]) into one risk value."""
    miss = 1.0
    for value in evidence.values():
        miss *= 1 - clamp(value)
    return round(1 - miss, 4)


def severity(value: float) -> str:
    return "critical" if value >= 0.85 else "high" if value >= 0.6 else "medium" if value >= 0.3 else "low"


def day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class DetectionAgent(ABC):
    """A LangGraph node that reads the shared ProductContext and contributes one AgentSignal.

    Failures are contained here so one broken detector degrades the report instead of the run.
    """

    name: str

    @abstractmethod
    def analyze(self, ctx: ProductContext) -> AgentSignal: ...

    async def __call__(self, state: PipelineState) -> dict:
        started = perf_counter()
        try:
            signal = await asyncio.to_thread(self.analyze, state["context"])
        except Exception as exc:
            log.exception("%s agent failed", self.name)
            signal = AgentSignal(
                agent=self.name, status="failed", error=str(exc), summary="Agent failed; excluded from scoring."
            )
        signal.agent = self.name
        signal.duration_ms = int((perf_counter() - started) * 1000)
        return {"signals": {self.name: signal}}

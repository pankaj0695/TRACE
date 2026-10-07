from typing import Annotated, TypedDict

from app.domain.models import AgentSignal, Assessment, ProductContext, TrustReport


def merge_signals(left: dict[str, AgentSignal], right: dict[str, AgentSignal]) -> dict[str, AgentSignal]:
    return {**left, **right}


class PipelineState(TypedDict, total=False):
    product_id: str
    context: ProductContext
    signals: Annotated[dict[str, AgentSignal], merge_signals]
    assessment: Assessment
    report: TrustReport

import json
import logging
from time import perf_counter

from pydantic import BaseModel

from app.domain.models import AgentSignal, Assessment, PolicyFinding, ProductContext, RiskTier, TrustReport
from app.llm.client import LLMClient, LLMUnavailable
from app.pipeline.state import PipelineState

log = logging.getLogger(__name__)

DETECTORS = ["anomaly", "authenticity", "network"]

POLICY = {
    "volume_spike": "Review Manipulation",
    "rating_skew": "Review Manipulation",
    "spike_rating_shift": "Review Manipulation",
    "unverified": "Verified Purchase Integrity",
    "near_duplicates": "Incentivized or Templated Reviews",
    "templated_language": "Incentivized or Templated Reviews",
    "cross_listing_copy": "Content Reuse Across Listings",
    "review_ring": "Coordinated Inauthentic Behavior",
    "new_account_cohort": "Coordinated Inauthentic Behavior",
    "seller_loyal_reviewers": "Seller Integrity",
}
ACTION = {
    "volume_spike": "Audit orders behind the review burst window before trusting the rating.",
    "rating_skew": "Suppress rating-based badges until the distribution is verified.",
    "spike_rating_shift": "Weight burst-window reviews down in the displayed average.",
    "unverified": "Hide unverified reviews from the default sort pending review.",
    "near_duplicates": "Remove near-duplicate reviews and check the accounts for incentives.",
    "templated_language": "Sample templated reviews for manual incentive screening.",
    "cross_listing_copy": "Investigate the sellers whose listings share copied review text.",
    "review_ring": "Escalate the co-review ring accounts to the abuse team for linkage analysis.",
    "new_account_cohort": "Rate-limit and verify the new-account cohort.",
    "seller_loyal_reviewers": "Request a seller audit for reviewer relationships.",
}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

SYSTEM = (
    "You are the orchestrator of TRACE, a marketplace trust-and-safety system. You receive structured evidence "
    "from detection agents and write a concise, factual brief for a human trust & safety reviewer. Never invent "
    "numbers; only use evidence provided. You triage and recommend; you never decide enforcement."
)


class _LLMReport(BaseModel):
    headline: str
    summary: str
    findings: list[PolicyFinding]
    recommendations: list[str]
    reviewer_note: str


class OrchestratorAgent:
    """Routes the pipeline, reconciles detector outputs and produces the reviewer-facing report."""

    name = "orchestrator"

    def __init__(self, llm: LLMClient, min_reviews: int):
        self.llm = llm
        self.min_reviews = min_reviews

    def route(self, state: PipelineState) -> list[str]:
        return DETECTORS if len(state["context"].reviews) >= self.min_reviews else ["scoring"]

    async def __call__(self, state: PipelineState) -> dict:
        started = perf_counter()
        ctx, signals, assessment = state["context"], state.get("signals", {}), state["assessment"]
        findings = self._policy_findings(signals)
        report = self._rule_report(ctx, assessment, signals, findings)
        if assessment.tier != RiskTier.INSUFFICIENT:
            try:
                raw = await self.llm.generate_json(
                    SYSTEM, self._prompt(ctx, assessment, signals, findings), _LLMReport.model_json_schema()
                )
                report = TrustReport(**_LLMReport.model_validate(raw).model_dump(), generated_by=self.llm.name)
            except (LLMUnavailable, ValueError) as exc:
                log.info("LLM report unavailable, using rule-based report: %s", exc)

        signal = AgentSignal(
            agent=self.name,
            confidence=1.0,
            summary=f"Report drafted by {report.generated_by}.",
            metrics={
                "generated_by": report.generated_by,
                "conflict": assessment.conflict,
                "failed_agents": [k for k, s in signals.items() if s.status == "failed"],
            },
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return {"report": report, "signals": {self.name: signal}}

    @staticmethod
    def _policy_findings(signals: dict[str, AgentSignal]) -> list[PolicyFinding]:
        items = [
            PolicyFinding(
                title=f.title, detail=f.detail, severity=f.severity, policy=POLICY.get(f.code, "General"), agent=agent
            )
            for agent, s in signals.items()
            for f in s.findings
        ]
        return sorted(items, key=lambda f: _SEVERITY_RANK[f.severity])

    def _rule_report(
        self, ctx: ProductContext, a: Assessment, signals: dict[str, AgentSignal], findings: list[PolicyFinding]
    ) -> TrustReport:
        if a.tier == RiskTier.INSUFFICIENT:
            return TrustReport(
                headline="Not enough review history to assess",
                summary=f"Only {len(ctx.reviews)} reviews are available; at least {self.min_reviews} are needed for a reliable read.",
                findings=[],
                recommendations=["Re-run once more reviews accumulate."],
                reviewer_note="No action suggested.",
                generated_by="rules",
            )
        codes = [f.code for s in signals.values() for f in s.findings]
        failed = [k for k, s in signals.items() if s.status == "failed"]
        note = (
            "Detectors disagree; weigh the evidence manually."
            if a.conflict
            else "Evidence is consistent across agents."
        )
        if failed:
            note += f" Partial analysis: {', '.join(failed)} failed."
        return TrustReport(
            headline=f"{a.tier.value.title()} risk: {findings[0].title}"
            if findings
            else "No material manipulation signals",
            summary=f"The listing scored {a.risk_score:.0f}/100 risk across {len(ctx.reviews)} reviews. "
            + " ".join(f"{s.summary.rstrip('.')}." for k, s in signals.items() if k in DETECTORS),
            findings=findings[:6],
            recommendations=list(dict.fromkeys(ACTION[c] for c in codes if c in ACTION))[:5]
            or ["No action needed; keep monitoring."],
            reviewer_note=note,
            generated_by="rules",
        )

    @staticmethod
    def _prompt(
        ctx: ProductContext, a: Assessment, signals: dict[str, AgentSignal], findings: list[PolicyFinding]
    ) -> str:
        evidence = {
            k: {
                "status": s.status,
                "risk": s.risk,
                "confidence": s.confidence,
                "summary": s.summary,
                "metrics": {m: v for m, v in s.metrics.items() if m != "evidence"},
            }
            for k, s in signals.items()
            if k in DETECTORS
        }
        return (
            f"PRODUCT: {ctx.product.title} | store: {ctx.product.store} | reviews analysed: {len(ctx.reviews)}\n"
            f"ASSESSMENT: {a.model_dump_json()}\n"
            f"AGENT EVIDENCE: {json.dumps(evidence, default=str)}\n"
            f"POLICY-MAPPED FINDINGS: {json.dumps([f.model_dump() for f in findings])}\n\n"
            "Write the brief. headline: one line with the risk tier and main issue. summary: 2-3 sentences. "
            "findings: keep the given findings (you may merge or reword, keep policy/agent/severity accurate), most severe first, max 5. "
            "recommendations: 2-4 concrete next steps for the reviewer. reviewer_note: mention detector conflicts or partial analysis if any."
        )

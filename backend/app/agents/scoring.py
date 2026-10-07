from app.domain.models import AgentSignal, Assessment, RiskTier
from app.pipeline.state import PipelineState

DETECTOR_WEIGHTS = {"anomaly": 0.35, "authenticity": 0.30, "network": 0.35}


class TrustScoringAgent:
    """Confidence-weighted aggregation of detector risks into a 0-100 score and tier."""

    name = "scoring"

    def __init__(
        self, weights: dict[str, float] = DETECTOR_WEIGHTS, conflict_gap: float = 0.6, peak_boost: float = 0.4
    ):
        self.weights = weights
        self.peak_boost = peak_boost
        self.conflict_gap = conflict_gap

    def assess(self, signals: dict[str, AgentSignal]) -> Assessment:
        usable = {k: s for k, s in signals.items() if k in self.weights and s.status == "ok"}
        effective = {k: self.weights[k] * s.confidence for k, s in usable.items()}
        total = sum(effective.values())
        if total == 0:
            return Assessment(
                risk_score=0,
                trust_score=0,
                tier=RiskTier.INSUFFICIENT,
                weights={},
                conflict=False,
                needs_manual_review=True,
            )

        mean_risk = sum(effective[k] * usable[k].risk for k in usable) / total
        # A single strong, confident detector should not be averaged away by quiet ones.
        peak_risk = max(usable[k].risk * usable[k].confidence for k in usable)
        risk = 100 * (mean_risk + self.peak_boost * max(0.0, peak_risk - mean_risk))
        confident = [s.risk for s in usable.values() if s.confidence >= 0.5]
        conflict = len(confident) > 1 and max(confident) - min(confident) >= self.conflict_gap
        tier = RiskTier.from_score(risk)
        degraded = any(signals.get(k) is None or signals[k].status != "ok" for k in self.weights)
        return Assessment(
            risk_score=round(risk, 1),
            trust_score=round(100 - risk, 1),
            tier=tier,
            weights={k: round(v / total, 3) for k, v in effective.items()},
            conflict=conflict,
            needs_manual_review=conflict or degraded or tier in (RiskTier.HIGH, RiskTier.CRITICAL),
        )

    async def __call__(self, state: PipelineState) -> dict:
        assessment = self.assess(state.get("signals", {}))
        signal = AgentSignal(
            agent=self.name,
            risk=assessment.risk_score / 100,
            confidence=1.0,
            summary=f"Risk {assessment.risk_score:.0f}/100 ({assessment.tier.value.replace('_', ' ')})"
            + (" - detectors disagree" if assessment.conflict else ""),
            metrics={"weights": assessment.weights, "conflict": assessment.conflict},
        )
        return {"assessment": assessment, "signals": {self.name: signal}}

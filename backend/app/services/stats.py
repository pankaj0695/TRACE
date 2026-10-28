from statistics import mean

from app.container import Container
from app.domain.models import RiskTier


def dashboard_stats(c: Container) -> dict:
    """Console KPIs; shared by the REST API and the MCP tools so both report identical numbers."""
    summaries = c.analysis.summaries()
    tiers = {t.value: 0 for t in RiskTier if t != RiskTier.INSUFFICIENT}
    for s in summaries:
        tiers[s.tier.value] = tiers.get(s.tier.value, 0) + 1
    return {
        **c.products.counts(),
        "analyzed": len(summaries),
        "flagged": tiers["high"] + tiers["critical"],
        "avg_trust": round(100 - mean(s.risk_score for s in summaries), 1) if summaries else None,
        "tiers": tiers,
        "recent": [{"product_id": s.product_id, "risk": s.risk_score} for s in summaries[-24:]],
    }

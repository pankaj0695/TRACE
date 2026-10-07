from collections import Counter
from statistics import mean

from app.agents.base import DetectionAgent, clamp, day, noisy_or, severity
from app.domain.models import AgentSignal, Finding, ProductContext

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


class AnomalyAgent(DetectionAgent):
    """Statistical anomalies in review volume, timing and rating distribution."""

    name = "anomaly"

    def analyze(self, ctx: ProductContext) -> AgentSignal:
        reviews = ctx.reviews
        n = len(reviews)
        ts = [r.ts for r in reviews]

        weeks = Counter((t - ts[0]) // WEEK_MS for t in ts)
        span = max(weeks) + 1
        weekly = [weeks.get(w, 0) for w in range(span)]
        baseline = mean(weekly)
        peak, lo, hi = self._peak_window(ts)
        spike_ratio = peak / max(baseline, 1.0)

        in_peak = reviews[lo : hi + 1]
        outside = reviews[:lo] + reviews[hi + 1 :]
        five = sum(r.rating >= 5 for r in reviews) / n
        five_peak = sum(r.rating >= 5 for r in in_peak) / len(in_peak)
        five_outside = sum(r.rating >= 5 for r in outside) / len(outside) if outside else five_peak
        verified = sum(r.verified for r in reviews) / n
        unverified_peak = sum(not r.verified for r in in_peak) / len(in_peak)
        busiest_day, busiest_count = Counter(day(t) for t in ts).most_common(1)[0]

        base_five = ctx.baselines.get("five_star_share", 0.57)
        base_verified = ctx.baselines.get("verified_rate", 0.93)
        evidence = {
            "volume_spike": clamp((peak / n - 0.15) / 0.35) if peak >= 8 and spike_ratio >= 4 else 0.0,
            "rating_skew": clamp((five - base_five - 0.15) / 0.3),
            "spike_rating_shift": clamp((five_peak - five_outside - 0.15) / 0.35) if peak >= 8 else 0.0,
            "unverified": clamp((base_verified - verified - 0.1) / 0.3),
        }

        findings = []
        if evidence["volume_spike"] > 0:
            findings.append(
                Finding(
                    code="volume_spike",
                    severity=severity(evidence["volume_spike"]),
                    title=f"Review burst: {peak} reviews in 7 days ({spike_ratio:.1f}x baseline)",
                    detail=f"Between {day(ts[lo])} and {day(ts[hi])} the listing received {peak} reviews ({peak / n:.0%} of its "
                    f"lifetime total) against a baseline of {baseline:.1f}/week.",
                    evidence={
                        "peak": peak,
                        "baseline_per_week": round(baseline, 2),
                        "start": day(ts[lo]),
                        "end": day(ts[hi]),
                    },
                )
            )
        if evidence["rating_skew"] > 0:
            findings.append(
                Finding(
                    code="rating_skew",
                    severity=severity(evidence["rating_skew"]),
                    title=f"{five:.0%} five-star ratings vs {base_five:.0%} category baseline",
                    detail="Rating distribution is unusually concentrated at 5 stars for this category.",
                    evidence={"five_star_share": round(five, 3), "baseline": round(base_five, 3)},
                )
            )
        if evidence["spike_rating_shift"] > 0:
            findings.append(
                Finding(
                    code="spike_rating_shift",
                    severity=severity(evidence["spike_rating_shift"]),
                    title=f"Burst window is {five_peak:.0%} five-star vs {five_outside:.0%} elsewhere",
                    detail="Ratings posted inside the burst are markedly more positive than the organic trend.",
                    evidence={"five_in_peak": round(five_peak, 3), "five_outside": round(five_outside, 3)},
                )
            )
        if evidence["unverified"] > 0:
            findings.append(
                Finding(
                    code="unverified",
                    severity=severity(evidence["unverified"]),
                    title=f"Only {verified:.0%} verified purchases (baseline {base_verified:.0%})",
                    detail="A large share of reviewers have no verified purchase of this product.",
                    evidence={"verified_rate": round(verified, 3), "baseline": round(base_verified, 3)},
                )
            )

        risk = noisy_or(evidence)
        return AgentSignal(
            agent=self.name,
            risk=risk,
            confidence=round(clamp(n / 50, 0.2, 1.0), 2),
            summary=findings[0].title if findings else "Review volume, timing and ratings look organic.",
            metrics={
                "spike_ratio": round(spike_ratio, 2),
                "peak_7d": peak,
                "baseline_per_week": round(baseline, 2),
                "five_star_share": round(five, 3),
                "verified_rate": round(verified, 3),
                "unverified_in_peak": round(unverified_peak, 3),
                "busiest_day": busiest_day,
                "busiest_day_count": busiest_count,
                "evidence": {k: round(v, 3) for k, v in evidence.items()},
            },
            findings=findings,
            artifacts={
                "weekly": [{"week": day(ts[0] + w * WEEK_MS), "count": c} for w, c in enumerate(weekly)],
                "peak": {"start": day(ts[lo]), "end": day(ts[hi])},
                "ratings": {str(s): sum(1 for r in reviews if round(r.rating) == s) for s in range(1, 6)},
                "baseline_five_star": round(base_five, 3),
            },
        )

    @staticmethod
    def _peak_window(ts: list[int]) -> tuple[int, int, int]:
        best, best_lo, best_hi, lo = 0, 0, 0, 0
        for hi, t in enumerate(ts):
            while t - ts[lo] >= WEEK_MS:
                lo += 1
            if hi - lo + 1 > best:
                best, best_lo, best_hi = hi - lo + 1, lo, hi
        return best, best_lo, best_hi

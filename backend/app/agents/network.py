from collections import Counter, defaultdict

import networkx as nx

from app.agents.base import DetectionAgent, clamp, noisy_or, severity
from app.domain.models import AgentSignal, Finding, ProductContext
from app.graph.store import GraphStore

WEEK_MS = 7 * 86_400_000
_MAX_REVIEWER_NODES = 90
_MAX_PRODUCT_NODES = 40


class NetworkAgent(DetectionAgent):
    """Coordinated behaviour in the reviewer knowledge graph: co-review rings, seller-loyal
    accounts and cohorts of brand-new accounts that arrive together."""

    name = "network"

    def __init__(self, graph: GraphStore, min_shared: int = 2):
        self.graph = graph
        self.min_shared = min_shared

    def analyze(self, ctx: ProductContext) -> AgentSignal:
        pid, store = ctx.product.id, ctx.product.store
        n = len(ctx.reviewers)
        edges = self.graph.neighborhood(pid)
        pairs = self.graph.co_review_pairs(pid, self.min_shared)

        ring_graph = nx.Graph()
        ring_graph.add_weighted_edges_from((p.a, p.b, p.shared) for p in pairs)
        rings = sorted((c for c in nx.connected_components(ring_graph) if len(c) >= 3), key=len, reverse=True)
        ring_members = set().union(*rings) if rings else set()

        loyal = {u for u, p in ctx.reviewers.items() if p.review_count >= 3 and p.store_share >= 0.8 and store}
        first_timers = sorted(r.ts for r in ctx.reviews if ctx.reviewers[r.user_id].first_ts == r.ts)
        cohort, cohort_span = self._max_in_window(first_timers), self._max_in_window([r.ts for r in ctx.reviews])
        # Share of the busiest week made of brand-new accounts, relative to how new the product's reviewers usually are.
        cohort_excess = cohort / max(cohort_span, 1) - len(first_timers) / max(len(ctx.reviews), 1)
        multi = sum(p.review_count > 1 for p in ctx.reviewers.values())

        evidence = {
            "review_rings": clamp((len(ring_members) / n) / 0.08) if n else 0.0,
            "seller_loyal": clamp((len(loyal) / n) / 0.1) if n else 0.0,
            "new_account_cohort": clamp((cohort_excess - 0.1) / 0.3) if cohort >= 8 else 0.0,
        }
        findings = []
        if rings:
            findings.append(
                Finding(
                    code="review_ring",
                    severity=severity(evidence["review_rings"]),
                    title=f"{len(rings)} co-review ring(s) with {len(ring_members)} accounts",
                    detail=f"Groups of reviewers repeatedly review the same other products together (>= {self.min_shared} shared).",
                    evidence={"rings": [sorted(r)[:12] for r in rings[:3]], "largest": len(rings[0])},
                )
            )
        if loyal:
            findings.append(
                Finding(
                    code="seller_loyal_reviewers",
                    severity=severity(evidence["seller_loyal"]),
                    title=f"{len(loyal)} reviewers review almost exclusively this seller",
                    detail=f"These accounts have 3+ reviews with >= 80% on {store}'s catalog.",
                    evidence={"reviewers": sorted(loyal)[:15]},
                )
            )
        if evidence["new_account_cohort"] > 0:
            findings.append(
                Finding(
                    code="new_account_cohort",
                    severity=severity(evidence["new_account_cohort"]),
                    title=f"{cohort} first-time accounts reviewed within one week",
                    detail="Accounts whose first-ever review is this product are over-represented in its busiest week.",
                    evidence={"cohort": cohort, "excess_share": round(cohort_excess, 3)},
                )
            )

        return AgentSignal(
            agent=self.name,
            risk=noisy_or(evidence),
            confidence=round(clamp(n / 40, 0.2, 1.0) * clamp(multi / 15, 0.2, 1.0), 2),
            summary=findings[0].title if findings else "No coordinated reviewer structure detected.",
            metrics={
                "graph_backend": self.graph.name,
                "reviewers": n,
                "multi_product_reviewers": multi,
                "co_review_pairs": len(pairs),
                "rings": len(rings),
                "ring_members": len(ring_members),
                "seller_loyal": len(loyal),
                "new_account_cohort": cohort,
                "evidence": {k: round(v, 3) for k, v in evidence.items()},
            },
            findings=findings,
            artifacts={"graph": self._graph_view(pid, store, edges, ring_members, loyal, pairs)},
        )

    @staticmethod
    def _max_in_window(ts: list[int]) -> int:
        best, lo = 0, 0
        for hi, t in enumerate(ts):
            while t - ts[lo] >= WEEK_MS:
                lo += 1
            best = max(best, hi - lo + 1)
        return best

    @staticmethod
    def _graph_view(pid, store, edges, ring_members, loyal, pairs) -> dict:
        """A bounded subgraph for the UI: the product, its most connected reviewers and their other products."""
        by_user: dict[str, list] = defaultdict(list)
        for e in edges:
            by_user[e.user_id].append(e)
        priority = lambda u: (u in ring_members, u in loyal, len(by_user[u]))  # noqa: E731
        reviewers = sorted(by_user, key=priority, reverse=True)[:_MAX_REVIEWER_NODES]
        product_degree = Counter(e.product_id for u in reviewers for e in by_user[u] if e.product_id != pid)
        products = {p for p, _ in product_degree.most_common(_MAX_PRODUCT_NODES)}
        stores = {e.product_id: e.store for u in reviewers for e in by_user[u]}

        nodes = [{"id": pid, "kind": "target", "label": store or pid}]
        nodes += [
            {
                "id": p,
                "kind": "product",
                "same_store": bool(store) and stores.get(p) == store,
                "label": stores.get(p) or p,
            }
            for p in products
        ]
        nodes += [
            {"id": u, "kind": "reviewer", "ring": u in ring_members, "loyal": u in loyal, "degree": len(by_user[u])}
            for u in reviewers
        ]
        links = [
            {"source": u, "target": e.product_id, "rating": e.rating}
            for u in reviewers
            for e in by_user[u]
            if e.product_id == pid or e.product_id in products
        ]
        kept = set(reviewers)
        links += [
            {"source": p.a, "target": p.b, "kind": "co_review", "shared": p.shared}
            for p in pairs
            if p.a in kept and p.b in kept
        ][:150]
        return {"nodes": nodes, "links": links, "truncated": len(by_user) > len(reviewers)}

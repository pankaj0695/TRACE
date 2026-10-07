import re
from collections import Counter, defaultdict

import numpy as np

from app.agents.base import DetectionAgent, clamp, day, noisy_or, severity
from app.domain.models import AgentSignal, Finding, ProductContext, Review
from app.retrieval.embedder import Embedder
from app.retrieval.lexical import LexicalIndex
from app.retrieval.text import TOKEN, is_generic, word_count

_STOP = set(
    "this that with have they them were very will would just really also like from your what when there these than been".split()
)
_MAX_REVIEWS = 800


def _text(r: Review) -> str:
    return f"{r.title}. {r.text}".strip(". ")


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


class AuthenticityAgent(DetectionAgent):
    """Linguistic authenticity via information retrieval: near-duplicate clusters (dense embeddings),
    text copied across listings (TF-IDF index), and templated / low-information reviews."""

    name = "authenticity"

    def __init__(self, index: LexicalIndex, embedder: Embedder | None):
        self.index = index
        self.embedder = embedder

    def analyze(self, ctx: ProductContext) -> AgentSignal:
        reviews = ctx.reviews[-_MAX_REVIEWS:]
        vocab = {t for t in TOKEN.findall(" ".join([ctx.product.title, *ctx.product.features]).lower())} - _STOP
        substantive = [r for r in reviews if word_count(_text(r)) >= 6]

        template_share = sum(is_generic(_text(r), vocab) for r in reviews) / len(reviews)
        template_baseline = self.index.generic_share

        clusters = self._duplicate_clusters(substantive)
        in_clusters = sum(len(c) for c in clusters)
        dup_share = in_clusters / max(len(substantive), 1)

        copies = self.index.cross_listing_matches(
            [r.id for r in substantive if word_count(r.text) >= 8], ctx.product.id, 0.9
        )
        copied_ids = {rid for rid, _ in copies}
        copy_share = len(copied_ids) / max(len(substantive), 1)

        phrases = self._shared_phrases(reviews)

        evidence = {
            "duplicates": clamp((dup_share - 0.02) / 0.15),
            "cross_listing": clamp(copy_share / 0.08),
            # Generic praise alone is weak evidence, so it can never saturate the signal.
            "templated": 0.7 * clamp((template_share - template_baseline - 0.05) / 0.4),
        }
        findings = []
        if evidence["duplicates"] > 0:
            findings.append(
                Finding(
                    code="near_duplicates",
                    severity=severity(evidence["duplicates"]),
                    title=f"{in_clusters} reviews form {len(clusters)} near-duplicate clusters",
                    detail="Different accounts posted semantically near-identical reviews, a common incentivized-review signature.",
                    evidence={"clusters": len(clusters), "reviews": in_clusters, "share": round(dup_share, 3)},
                )
            )
        if evidence["cross_listing"] > 0:
            findings.append(
                Finding(
                    code="cross_listing_copy",
                    severity=severity(evidence["cross_listing"]),
                    title=f"{len(copied_ids)} review texts reappear on other listings",
                    detail="Near-verbatim review text was found on unrelated products under different accounts.",
                    evidence={"reviews": len(copied_ids), "share": round(copy_share, 3)},
                )
            )
        if evidence["templated"] > 0:
            findings.append(
                Finding(
                    code="templated_language",
                    severity=severity(evidence["templated"]),
                    title=f"{template_share:.0%} of reviews are generic or templated",
                    detail="Short superlative reviews with no product-specific detail exceed the category norm.",
                    evidence={"share": round(template_share, 3), "baseline": round(template_baseline, 3)},
                )
            )

        authenticity = round(1 - noisy_or(evidence), 3)
        return AgentSignal(
            agent=self.name,
            risk=noisy_or(evidence),
            confidence=round(clamp(len(substantive) / 30, 0.2, 1.0), 2),
            summary=findings[0].title if findings else "Review language looks varied and product-specific.",
            metrics={
                "authenticity_score": authenticity,
                "duplicate_share": round(dup_share, 3),
                "cross_listing_share": round(copy_share, 3),
                "templated_share": round(template_share, 3),
                "similarity_engine": self.embedder.name if self.embedder else "tf-idf",
                "evidence": {k: round(v, 3) for k, v in evidence.items()},
            },
            findings=findings,
            artifacts={
                "clusters": [self._cluster_view(c) for c in clusters[:6]],
                "copies": [
                    {
                        "review_id": rid,
                        "other_review_id": hit.review_id,
                        "other_product_id": hit.product_id,
                        "score": round(hit.score, 3),
                    }
                    for rid, hit in sorted(copies, key=lambda x: -x[1].score)[:10]
                ],
                "phrases": phrases,
            },
        )

    def _duplicate_clusters(self, reviews: list[Review]) -> list[list[Review]]:
        if len(reviews) < 2:
            return []
        if self.embedder:
            vectors, threshold = self.embedder.embed([_text(r) for r in reviews]), 0.93
            sims = vectors @ vectors.T
        else:
            vectors, threshold = self.index.vectors([r.id for r in reviews]), 0.8
            sims = (vectors @ vectors.T).toarray()
        uf = _UnionFind(len(reviews))
        for i, j in zip(*np.where(np.triu(sims, 1) >= threshold), strict=False):
            if reviews[i].user_id != reviews[j].user_id:
                uf.union(i, j)
        groups = defaultdict(list)
        for i, r in enumerate(reviews):
            groups[uf.find(i)].append(r)
        return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)

    @staticmethod
    def _shared_phrases(reviews: list[Review], n: int = 4, min_users: int = 3) -> list[dict]:
        users_by_gram: dict[str, set[str]] = defaultdict(set)
        for r in reviews:
            words = re.findall(r"[a-z']+", r.text.lower())
            for gram in {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}:
                users_by_gram[gram].add(r.user_id)
        counts = Counter({g: len(u) for g, u in users_by_gram.items() if len(u) >= min_users})
        return [{"phrase": g, "reviewers": c} for g, c in counts.most_common(8)]

    @staticmethod
    def _cluster_view(cluster: list[Review]) -> dict:
        return {
            "size": len(cluster),
            "reviews": [
                {"id": r.id, "user_id": r.user_id, "rating": r.rating, "date": day(r.ts), "text": _text(r)[:280]}
                for r in cluster[:4]
            ],
        }

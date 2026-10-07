from pydantic import BaseModel

from app.data.repositories import ProductRepository, ReviewRepository
from app.domain.models import Product, Review
from app.retrieval.embedder import Embedder
from app.retrieval.lexical import LexicalIndex


class SearchResult(BaseModel):
    review: Review
    product: Product | None
    lexical_score: float
    score: float


class ReviewSearch:
    """Two-stage retrieval: TF-IDF recall over the corpus, then dense semantic re-ranking."""

    def __init__(
        self, index: LexicalIndex, embedder: Embedder | None, reviews: ReviewRepository, products: ProductRepository
    ):
        self.index = index
        self.embedder = embedder
        self.reviews = reviews
        self.products = products

    def search(self, query: str, k: int = 20, recall: int = 150) -> list[SearchResult]:
        hits = self.index.search(query, recall)
        if not hits:
            return []
        reviews = self.reviews.by_ids([h.review_id for h in hits])
        scored = [(h, reviews[h.review_id]) for h in hits if h.review_id in reviews]
        if self.embedder:
            vectors = self.embedder.embed([query] + [f"{r.title}. {r.text}" for _, r in scored])
            dense = vectors[1:] @ vectors[0]
            ranked = [(h, r, 0.7 * float(d) + 0.3 * h.score) for (h, r), d in zip(scored, dense, strict=False)]
        else:
            ranked = [(h, r, h.score) for h, r in scored]
        ranked.sort(key=lambda x: x[2], reverse=True)
        top = ranked[:k]
        products = self.products.get_many(r.product_id for _, r, _ in top)
        return [
            SearchResult(
                review=r, product=products.get(r.product_id), lexical_score=round(h.score, 4), score=round(s, 4)
            )
            for h, r, s in top
        ]

import asyncio
from time import perf_counter

from app.agents.base import day
from app.data.repositories import ProductRepository, ReviewRepository
from app.domain.models import AgentSignal, ProductContext
from app.pipeline.state import PipelineState


class ProductNotFound(LookupError):
    pass


class IngestionAgent:
    """Assembles the product, its reviews and reviewer profiles into one normalised context."""

    name = "ingestion"

    def __init__(self, products: ProductRepository, reviews: ReviewRepository, baselines: dict[str, float]):
        self.products = products
        self.reviews = reviews
        self.baselines = baselines

    def load(self, product_id: str) -> ProductContext:
        product = self.products.get(product_id)
        if product is None:
            raise ProductNotFound(product_id)
        reviews = self.reviews.for_product(product_id)
        reviewers = self.reviews.reviewer_profiles(sorted({r.user_id for r in reviews}), product.store)
        return ProductContext(product=product, reviews=reviews, reviewers=reviewers, baselines=self.baselines)

    async def __call__(self, state: PipelineState) -> dict:
        started = perf_counter()
        ctx = await asyncio.to_thread(self.load, state["product_id"])
        reviews = ctx.reviews
        n = len(reviews)
        metrics = {
            "reviews": n,
            "reviewers": len(ctx.reviewers),
            "verified_rate": round(sum(r.verified for r in reviews) / n, 3) if n else 0,
            "avg_rating": round(sum(r.rating for r in reviews) / n, 2) if n else 0,
            "first_review": day(reviews[0].ts) if n else None,
            "last_review": day(reviews[-1].ts) if n else None,
        }
        signal = AgentSignal(
            agent=self.name,
            confidence=1.0,
            metrics=metrics,
            summary=f"Loaded {n} reviews from {len(ctx.reviewers)} reviewers for {ctx.product.store or 'unknown store'}.",
            duration_ms=int((perf_counter() - started) * 1000),
        )
        return {"context": ctx, "signals": {self.name: signal}}

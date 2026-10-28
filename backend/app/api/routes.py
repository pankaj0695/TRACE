import csv
import io
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.container import Container
from app.domain.models import Analysis, Product
from app.pipeline.graph import STAGES
from app.retrieval.search import SearchResult
from app.services.stats import dashboard_stats

router = APIRouter(prefix="/api")


def container(request: Request) -> Container:
    c = getattr(request.app.state, "container", None)
    if c is None:
        raise HTTPException(503, getattr(request.app.state, "startup_error", None) or "Service is starting")
    return c


ContainerDep = Annotated[Container, Depends(container)]


@router.get("/health")
def health(request: Request) -> dict:
    c = getattr(request.app.state, "container", None)
    if c is None:
        return {"status": "degraded", "error": getattr(request.app.state, "startup_error", None) or "starting"}
    return {
        "status": "ok",
        "graph_backend": c.graph.name,
        "embedder": c.embedder.name if c.embedder else "tf-idf",
        "llm": c.llm.name,
        "indexed_reviews": len(c.index),
        "stages": STAGES,
        "mcp": {"enabled": c.settings.mcp_enabled, "endpoint": "/mcp"},
    }


@router.get("/stats")
def stats(c: ContainerDep) -> dict:
    return dashboard_stats(c)


@router.get("/products")
def list_products(
    c: ContainerDep,
    q: str = "",
    tier: str | None = None,
    sort: Literal["risk", "reviews", "spike", "title"] = "risk",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    items, total = c.products.search(q.strip(), tier, sort, limit, offset)
    return {"items": items, "total": total}


@router.get("/products/{product_id}")
def get_product(product_id: str, c: ContainerDep) -> Product:
    product = c.products.get(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.get("/products/{product_id}/analysis")
def latest_analysis(product_id: str, c: ContainerDep) -> Analysis:
    analysis = c.analysis.latest(product_id)
    if not analysis:
        raise HTTPException(404, "No analysis yet")
    return analysis


@router.post("/products/{product_id}/analysis")
async def run_analysis(product_id: str, c: ContainerDep) -> Analysis:
    try:
        return await c.analysis.run(product_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/products/{product_id}/analysis/stream")
async def stream_analysis(product_id: str, c: ContainerDep) -> StreamingResponse:
    """Server-sent events: one `stage` event per agent transition, then a final `result`."""
    if not c.products.get(product_id):
        raise HTTPException(404, "Product not found")

    async def events():
        async for event in c.analysis.stream(product_id):
            yield f"event: {event['event']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/search/reviews")
def search_reviews(
    c: ContainerDep, q: str = Query(..., min_length=2), k: int = Query(20, ge=1, le=50)
) -> list[SearchResult]:
    return c.search.search(q, k)


@router.get("/analyses/export.csv")
def export_csv(c: ContainerDep) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["product_id", "title", "store", "risk_score", "tier", "headline", "analyzed_at"])
    for s in c.analysis.summaries():
        a = c.analysis.latest(s.product_id)
        writer.writerow(
            [
                s.product_id,
                a.product.title,
                a.product.store,
                s.risk_score,
                s.tier.value,
                a.report.headline,
                s.created_at.isoformat(),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=trace-audit.csv"}
    )

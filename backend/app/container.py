"""Composition root: the only place that knows concrete implementations."""

import logging
from dataclasses import dataclass

from app.agents.anomaly import AnomalyAgent
from app.agents.authenticity import AuthenticityAgent
from app.agents.ingestion import IngestionAgent
from app.agents.network import NetworkAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.scoring import TrustScoringAgent
from app.core.config import Settings
from app.data.database import Database
from app.data.repositories import AnalysisRepository, ProductRepository, ReviewRepository
from app.graph.store import GraphStore, ReviewEdge, create_graph_store
from app.llm.client import LLMClient, create_llm
from app.pipeline.graph import build_pipeline
from app.retrieval.embedder import Embedder, create_embedder
from app.retrieval.lexical import LexicalIndex
from app.retrieval.search import ReviewSearch
from app.services.analysis import AnalysisService

log = logging.getLogger(__name__)


class DatasetMissing(RuntimeError):
    pass


@dataclass
class Container:
    settings: Settings
    products: ProductRepository
    reviews: ReviewRepository
    graph: GraphStore
    index: LexicalIndex
    embedder: Embedder | None
    llm: LLMClient
    analysis: AnalysisService
    search: ReviewSearch

    def close(self) -> None:
        self.graph.close()


def build_container(settings: Settings) -> Container:
    if not settings.db_path.exists():
        raise DatasetMissing(f"{settings.db_path} not found - run `python -m scripts.build_dataset` first")
    db = Database(settings.db_path)
    db.init_schema()
    products, reviews, analyses = ProductRepository(db), ReviewRepository(db), AnalysisRepository(db)

    graph = create_graph_store(settings.graph_backend, settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    graph.load([ReviewEdge(*row) for row in reviews.all_edges()])
    index = LexicalIndex(reviews.all_texts())
    log.info("lexical index ready: %d reviews", len(index))
    embedder = create_embedder(settings.embedder, settings.embedding_model)
    llm = create_llm(
        settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_model, settings.llm_timeout_s
    )

    orchestrator = OrchestratorAgent(llm, settings.min_reviews)
    pipeline = build_pipeline(
        IngestionAgent(products, reviews, products.baselines()),
        AnomalyAgent(),
        AuthenticityAgent(index, embedder),
        NetworkAgent(graph),
        TrustScoringAgent(),
        orchestrator,
    )
    return Container(
        settings=settings,
        products=products,
        reviews=reviews,
        graph=graph,
        index=index,
        embedder=embedder,
        llm=llm,
        analysis=AnalysisService(pipeline, orchestrator.route, products, analyses),
        search=ReviewSearch(index, embedder, reviews, products),
    )

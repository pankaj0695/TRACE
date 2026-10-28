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
from app.governance.egress import GovernedLLM
from app.governance.policy import approved_processors
from app.governance.services import GovernanceServices
from app.data.repositories import AnalysisRepository, ProductRepository, ReviewRepository
from app.graph.store import GraphStore, ReviewEdge, create_graph_store
from app.llm.client import DisabledLLM, LLMClient, create_llm
from app.pipeline.graph import build_pipeline
from app.retrieval.embedder import Embedder, create_embedder
from app.retrieval.lexical import LexicalIndex
from app.retrieval.search import ReviewSearch
from app.services.analysis import AnalysisService

log = logging.getLogger(__name__)


class DatasetMissing(RuntimeError):
    pass


def _missing_message(settings: Settings) -> str:
    from app.core.config import db_candidates

    looked = "\n  - ".join(str(p) for p in db_candidates())
    return (
        f"Working-set database not found at {settings.db_path}.\nSearched:\n  - {looked}\n"
        "Fix: place trace.db in <repo>/data, set TRACE_DB_PATH / TRACE_DATA_DIR in backend/.env, or build it with\n"
        "  python -m scripts.build_dataset --reviews ../data/Amazon_Fashion.jsonl --meta ../data/meta_Amazon_Fashion.jsonl"
    )


@dataclass
class Container:
    settings: Settings
    db: Database
    products: ProductRepository
    reviews: ReviewRepository
    graph: GraphStore
    index: LexicalIndex
    embedder: Embedder | None
    llm: LLMClient
    analysis: AnalysisService
    search: ReviewSearch
    governance: GovernanceServices

    def close(self) -> None:
        self.graph.close()

    def apply_erasure(self, user_id: str) -> None:
        """Propagate an erasure to every in-memory derivative of the data (graph, text index) and refresh lineage."""
        self.graph.delete_reviewer(user_id)
        self.index.rebuild(self.reviews.all_texts())
        self.governance.refresh_dataset()


def _is_local(uri: str) -> bool:
    host = uri.split("://", 1)[-1].split("@")[-1].split(":")[0].split("/")[0]
    return host in ("localhost", "127.0.0.1", "::1", "neo4j")


def build_container(settings: Settings) -> Container:
    if not settings.db_path.is_file():
        raise DatasetMissing(_missing_message(settings))
    db = Database(settings.db_path)
    db.init_schema()
    products, reviews, analyses = ProductRepository(db), ReviewRepository(db), AnalysisRepository(db)
    if products.counts()["monitored"] == 0:
        raise DatasetMissing(f"{settings.db_path} exists but has no monitored products; rebuild it with scripts.build_dataset")

    governance = GovernanceServices(settings, db)
    backend = settings.graph_backend
    if backend == "neo4j" and not _is_local(settings.neo4j_uri) and "neo4j" not in approved_processors(settings):
        log.warning("Hosted Neo4j (%s) is not an approved processor; using the in-process graph. "
                    "Add 'neo4j' to TRACE_APPROVED_PROCESSORS after review to enable it.", settings.neo4j_uri.split("@")[-1])
        backend = "networkx"
    graph = create_graph_store(backend, settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    graph.load([ReviewEdge(*row) for row in reviews.all_edges()])
    index = LexicalIndex(reviews.all_texts())
    log.info("lexical index ready: %d reviews", len(index))
    embedder = create_embedder(settings.embedder, settings.embedding_model)
    llm = create_llm(
        settings.gemini_api_key, settings.gemini_model, settings.gemini_fallback_model, settings.llm_timeout_s
    )

    if not isinstance(llm, DisabledLLM):  # every external call goes through the egress guard
        llm = GovernedLLM(llm, settings, governance.pseudonyms, governance.ledger)

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
        db=db,
        products=products,
        reviews=reviews,
        graph=graph,
        index=index,
        embedder=embedder,
        llm=llm,
        analysis=AnalysisService(pipeline, orchestrator.route, products, analyses, governance.lineage),
        search=ReviewSearch(index, embedder, reviews, products),
        governance=governance,
    )

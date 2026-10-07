"""Knowledge-graph access for the reviewer network.

Graph model: (Reviewer)-[:REVIEWED {rating, ts}]->(Product)-[:SOLD_BY]->(Store).
Two interchangeable backends share one protocol: an in-process NetworkX graph (zero setup)
and Neo4j (Cypher). The Network agent depends only on the protocol.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

import networkx as nx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewEdge:
    user_id: str
    product_id: str
    store: str | None
    rating: float
    ts: int


@dataclass(frozen=True)
class CoReviewPair:
    a: str
    b: str
    shared: int


class GraphStore(Protocol):
    name: str

    def load(self, edges: list[ReviewEdge]) -> None: ...

    def neighborhood(self, product_id: str) -> list[ReviewEdge]:
        """Every review written by anyone who reviewed `product_id`."""

    def co_review_pairs(self, product_id: str, min_shared: int) -> list[CoReviewPair]:
        """Reviewer pairs of `product_id` who also reviewed >= min_shared other products together."""

    def close(self) -> None: ...


class NetworkXGraphStore:
    name = "networkx"

    def __init__(self) -> None:
        self.graph = nx.Graph()

    def load(self, edges: list[ReviewEdge]) -> None:
        g = nx.Graph()
        for e in edges:
            g.add_node(("r", e.user_id))
            g.add_node(("p", e.product_id), store=e.store)
            g.add_edge(("r", e.user_id), ("p", e.product_id), rating=e.rating, ts=e.ts)
        self.graph = g
        log.info("networkx graph loaded: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())

    def neighborhood(self, product_id: str) -> list[ReviewEdge]:
        node = ("p", product_id)
        if node not in self.graph:
            return []
        edges = []
        for reviewer in self.graph.neighbors(node):
            for product in self.graph.neighbors(reviewer):
                data = self.graph.edges[reviewer, product]
                edges.append(
                    ReviewEdge(
                        reviewer[1], product[1], self.graph.nodes[product].get("store"), data["rating"], data["ts"]
                    )
                )
        return edges

    def co_review_pairs(self, product_id: str, min_shared: int) -> list[CoReviewPair]:
        node = ("p", product_id)
        if node not in self.graph:
            return []
        shared: dict[tuple[str, str], int] = defaultdict(int)
        for product in {p for r in self.graph.neighbors(node) for p in self.graph.neighbors(r)} - {node}:
            reviewers = sorted(r[1] for r in self.graph.neighbors(product) if self.graph.has_edge(r, node))
            for i, a in enumerate(reviewers):
                for b in reviewers[i + 1 :]:
                    shared[(a, b)] += 1
        return [CoReviewPair(a, b, n) for (a, b), n in shared.items() if n >= min_shared]

    def close(self) -> None:
        pass


class Neo4jGraphStore:
    name = "neo4j"

    _NEIGHBORHOOD = """
    MATCH (:Product {id: $pid})<-[:REVIEWED]-(u:Reviewer)
    MATCH (u)-[r:REVIEWED]->(q:Product)
    OPTIONAL MATCH (q)-[:SOLD_BY]->(s:Store)
    RETURN u.id AS user_id, q.id AS product_id, s.name AS store, r.rating AS rating, r.ts AS ts
    """
    _CO_REVIEW = """
    MATCH (p:Product {id: $pid})<-[:REVIEWED]-(a:Reviewer)-[:REVIEWED]->(q:Product)<-[:REVIEWED]-(b:Reviewer)-[:REVIEWED]->(p)
    WHERE a.id < b.id AND q <> p
    WITH a, b, count(DISTINCT q) AS shared WHERE shared >= $min_shared
    RETURN a.id AS a, b.id AS b, shared
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver.verify_connectivity()

    def load(self, edges: list[ReviewEdge]) -> None:
        with self.driver.session() as s:
            if s.run("MATCH (r:Reviewer) RETURN count(r) AS n").single()["n"] > 0:
                return
            for label in ("Reviewer", "Product"):
                s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Store) REQUIRE n.name IS UNIQUE")
            rows = [e.__dict__ for e in edges]
            for i in range(0, len(rows), 5000):
                s.run(
                    """
                    UNWIND $rows AS row
                    MERGE (u:Reviewer {id: row.user_id})
                    MERGE (p:Product {id: row.product_id})
                    MERGE (u)-[r:REVIEWED]->(p) SET r.rating = row.rating, r.ts = row.ts
                    WITH p, row WHERE row.store IS NOT NULL
                    MERGE (s:Store {name: row.store})
                    MERGE (p)-[:SOLD_BY]->(s)
                    """,
                    rows=rows[i : i + 5000],
                )
        log.info("neo4j graph loaded with %d review edges", len(edges))

    def neighborhood(self, product_id: str) -> list[ReviewEdge]:
        with self.driver.session() as s:
            return [ReviewEdge(**r.data()) for r in s.run(self._NEIGHBORHOOD, pid=product_id)]

    def co_review_pairs(self, product_id: str, min_shared: int) -> list[CoReviewPair]:
        with self.driver.session() as s:
            return [CoReviewPair(**r.data()) for r in s.run(self._CO_REVIEW, pid=product_id, min_shared=min_shared)]

    def close(self) -> None:
        self.driver.close()


def create_graph_store(backend: str, uri: str, user: str, password: str) -> GraphStore:
    if backend == "neo4j":
        try:
            return Neo4jGraphStore(uri, user, password)
        except Exception as exc:  # the app must stay usable when Neo4j is down
            log.warning("Neo4j unavailable (%s); falling back to NetworkX", exc)
    return NetworkXGraphStore()

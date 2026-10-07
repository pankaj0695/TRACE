import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Literal

from app.data.database import Database
from app.domain.models import Analysis, AnalysisSummary, Product, Review, ReviewerProfile, RiskTier

SortKey = Literal["risk", "reviews", "spike", "title"]
_SORT_SQL: dict[str, str] = {
    "risk": "a.risk_score IS NULL, a.risk_score DESC, p.spike_ratio DESC",
    "reviews": "p.review_count DESC",
    "spike": "p.spike_ratio DESC",
    "title": "p.title COLLATE NOCASE",
}


def _chunks(items: list[str], size: int = 900) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _product(row) -> Product:
    data = dict(row)
    data["features"] = json.loads(data.get("features") or "[]")
    return Product.model_validate(data)


class ProductRepository:
    def __init__(self, db: Database):
        self.db = db

    def search(self, query: str, tier: str | None, sort: SortKey, limit: int, offset: int) -> tuple[list[dict], int]:
        where, params = ["p.is_focus = 1"], []
        if query:
            where.append("(p.title LIKE ? OR p.store LIKE ? OR p.id = ?)")
            params += [f"%{query}%", f"%{query}%", query]
        if tier == "unscanned":
            where.append("a.tier IS NULL")
        elif tier:
            where.append("a.tier = ?")
            params.append(tier)
        base = f"FROM products p LEFT JOIN analyses a ON a.product_id = p.id WHERE {' AND '.join(where)}"
        with self.db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT p.*, a.risk_score, a.tier, a.created_at {base} ORDER BY {_SORT_SQL[sort]} LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        items = []
        for row in rows:
            data = dict(row)
            scan = {k: data.pop(k) for k in ("risk_score", "tier", "created_at")}
            items.append({"product": _product(data), "scan": scan if scan["tier"] else None})
        return items, total

    def get(self, product_id: str) -> Product | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _product(row) if row else None

    def get_many(self, product_ids: Iterable[str]) -> dict[str, Product]:
        ids, found = list(set(product_ids)), {}
        with self.db.connect() as conn:
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(f"SELECT * FROM products WHERE id IN ({marks})", chunk):
                    found[row["id"]] = _product(row)
        return found

    def baselines(self) -> dict[str, float]:
        with self.db.connect() as conn:
            return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM baselines")}

    def counts(self) -> dict[str, int]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT (SELECT COUNT(*) FROM products WHERE is_focus = 1) AS monitored,"
                " (SELECT COUNT(*) FROM reviews) AS reviews,"
                " (SELECT COUNT(DISTINCT user_id) FROM reviews) AS reviewers"
            ).fetchone()
        return dict(row)


class ReviewRepository:
    def __init__(self, db: Database):
        self.db = db

    def for_product(self, product_id: str) -> list[Review]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE product_id = ? ORDER BY ts", (product_id,)).fetchall()
        return [Review.model_validate(dict(r)) for r in rows]

    def by_ids(self, review_ids: list[int]) -> dict[int, Review]:
        found = {}
        with self.db.connect() as conn:
            for chunk in _chunks([str(i) for i in review_ids]):
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(f"SELECT * FROM reviews WHERE id IN ({marks})", chunk):
                    found[row["id"]] = Review.model_validate(dict(row))
        return found

    def all_texts(self) -> list[tuple[int, str, str, str]]:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT id, product_id, user_id, COALESCE(title,'') || '. ' || COALESCE(text,'') FROM reviews ORDER BY id"
            ).fetchall()

    def all_edges(self) -> list[tuple[str, str, str | None, float, int]]:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT r.user_id, r.product_id, p.store, r.rating, r.ts FROM reviews r JOIN products p ON p.id = r.product_id"
            ).fetchall()

    def reviewer_profiles(self, user_ids: list[str], store: str | None) -> dict[str, ReviewerProfile]:
        stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "first": None, "stores": set(), "same": 0, "ver": 0})
        with self.db.connect() as conn:
            for chunk in _chunks(user_ids):
                marks = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT r.user_id, r.ts, r.verified, p.store FROM reviews r JOIN products p ON p.id = r.product_id"
                    f" WHERE r.user_id IN ({marks})",
                    chunk,
                )
                for uid, ts, verified, s in rows:
                    st = stats[uid]
                    st["n"] += 1
                    st["first"] = ts if st["first"] is None else min(st["first"], ts)
                    st["stores"].add(s)
                    st["same"] += int(store is not None and s == store)
                    st["ver"] += verified
        return {
            uid: ReviewerProfile(
                user_id=uid,
                review_count=s["n"],
                first_ts=s["first"],
                distinct_stores=len(s["stores"]),
                store_share=s["same"] / s["n"],
                verified_rate=s["ver"] / s["n"],
            )
            for uid, s in stats.items()
        }


class AnalysisRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, analysis: Analysis) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?)",
                (
                    analysis.product.id,
                    analysis.assessment.risk_score,
                    analysis.assessment.tier.value,
                    analysis.created_at.isoformat(),
                    analysis.model_dump_json(),
                ),
            )

    def get(self, product_id: str) -> Analysis | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT payload FROM analyses WHERE product_id = ?", (product_id,)).fetchone()
        return Analysis.model_validate_json(row["payload"]) if row else None

    def summaries(self) -> list[AnalysisSummary]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT product_id, risk_score, tier, created_at FROM analyses ORDER BY created_at"
            ).fetchall()
        return [
            AnalysisSummary(
                product_id=r[0], risk_score=r[1], tier=RiskTier(r[2]), created_at=datetime.fromisoformat(r[3])
            )
            for r in rows
        ]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

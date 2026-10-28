"""Data-quality controls: dataset-level checks, per-product input checks, and dataset versioning for lineage."""

import hashlib
import json
from datetime import datetime, timezone

from app.data.database import Database
from app.domain.models import ProductContext
from app.governance.policy import catalog_gaps
from app.mcp.governance import _EMAIL, _PHONE

_MIN_TS = 788_918_400_000  # 1995-01-01 in ms: earlier than any online review
Check = dict


def _check(name: str, value, ok: bool, warn: bool = False, detail: str = "") -> Check:
    return {"check": name, "status": "pass" if ok else ("warn" if warn else "fail"), "value": value, "detail": detail}


def schema_of(db: Database) -> dict[str, list[str]]:
    with db.connect() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")] for t in tables}


def dataset_fingerprint(db: Database) -> dict:
    """Content-derived version id of the source data (stable across analysis/audit writes)."""
    with db.connect() as conn:
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(ts),0) ts_sum, COALESCE(SUM(LENGTH(text)),0) chars, COUNT(DISTINCT user_id) u FROM reviews"
        ).fetchone()
        prods = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(review_count),0) rc FROM products").fetchone()
        base = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM baselines")}
    basis = {"reviews": tuple(agg), "products": tuple(prods), "baselines": base}
    return {
        "version": hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16],
        "reviews": agg["n"],
        "reviewers": agg["u"],
        "products": prods["n"],
        "source": "Amazon Reviews'23 - Fashion (McAuley Lab)",
    }


def product_quality(ctx: ProductContext) -> dict:
    """Input checks for one analysis run; embedded in the analysis lineage."""
    n = len(ctx.reviews) or 1
    bad_rating = sum(not 1 <= r.rating <= 5 for r in ctx.reviews)
    empty = sum(len((r.text or "").strip()) == 0 for r in ctx.reviews)
    future = sum(r.ts > datetime.now(timezone.utc).timestamp() * 1000 for r in ctx.reviews)
    issues = []
    if bad_rating:
        issues.append(f"{bad_rating} ratings outside 1-5")
    if empty / n > 0.3:
        issues.append(f"{empty / n:.0%} of reviews have no text; authenticity confidence is reduced")
    if future:
        issues.append(f"{future} reviews dated in the future")
    if not ctx.baselines:
        issues.append("corpus baselines missing; anomaly agent used defaults")
    return {"reviews": len(ctx.reviews), "empty_text_share": round(empty / n, 3), "rating_out_of_range": bad_rating,
            "future_dated": future, "status": "warn" if issues else "pass", "issues": issues}  # fmt: skip


class QualityService:
    def __init__(self, db: Database):
        self.db = db

    def report(self) -> dict:
        checks: list[Check] = []
        with self.db.connect() as conn:
            q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
            n_reviews = max(q("SELECT COUNT(*) FROM reviews"), 1)
            checks.append(_check("monitored_products_present", q("SELECT COUNT(*) FROM products WHERE is_focus=1"), q("SELECT COUNT(*) FROM products WHERE is_focus=1") > 0))
            orphans = q("SELECT COUNT(*) FROM reviews r LEFT JOIN products p ON p.id=r.product_id WHERE p.id IS NULL")
            checks.append(_check("referential_integrity_reviews_to_products", orphans, orphans == 0))
            bad = q("SELECT COUNT(*) FROM reviews WHERE rating < 1 OR rating > 5")
            checks.append(_check("rating_range_1_to_5", bad, bad == 0))
            bad_ts = q(f"SELECT COUNT(*) FROM reviews WHERE ts < {_MIN_TS} OR ts > {int(datetime.now(timezone.utc).timestamp() * 1000)}")
            checks.append(_check("timestamps_plausible", bad_ts, bad_ts == 0))
            empty = q("SELECT COUNT(*) FROM reviews WHERE TRIM(COALESCE(text,'')) = ''") / n_reviews
            checks.append(_check("empty_review_text_share", round(empty, 4), empty < 0.05, empty < 0.2, "threshold 5% warn-free"))
            dupes = q("SELECT COUNT(*) FROM (SELECT 1 FROM reviews GROUP BY user_id, product_id, ts HAVING COUNT(*) > 1)")
            checks.append(_check("duplicate_review_rows", dupes, dupes == 0, True))
            checks.append(_check("baselines_present", q("SELECT COUNT(*) FROM baselines"), q("SELECT COUNT(*) FROM baselines") >= 2))
            emails = q("SELECT COUNT(*) FROM reviews WHERE text LIKE '%@%'")
            checks.append(_check("pii_candidates_in_review_text", emails, emails == 0, True, "rows with '@'; redacted on output, consider cleansing at build time"))
            stale = q("SELECT COUNT(*) FROM analyses a JOIN products p ON p.id=a.product_id WHERE p.review_count = 0")
            checks.append(_check("analyses_without_source_data", stale, stale == 0, True))
        phone_hits = 0
        with self.db.connect() as conn:
            for (text,) in conn.execute("SELECT text FROM reviews WHERE text GLOB '*[0-9][0-9][0-9]*[0-9][0-9][0-9]*[0-9][0-9][0-9]*' LIMIT 20000"):
                phone_hits += bool(_PHONE.search(text or "") or _EMAIL.search(text or ""))
        checks.append(_check("pii_regex_hits_sample_20k", phone_hits, phone_hits == 0, True, "emails/phones detected in the first 20k candidate rows"))
        gaps = catalog_gaps(schema_of(self.db))
        checks.append(_check("data_catalogue_covers_schema", gaps, not gaps, False, "every column must be classified in governance/policy.py"))
        statuses = {c["status"] for c in checks}
        return {"overall": "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass",
                "dataset": dataset_fingerprint(self.db), "checks": checks,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}  # fmt: skip


__all__ = ["QualityService", "dataset_fingerprint", "product_quality", "schema_of"]

"""Build the TRACE working set (SQLite) from the raw Amazon Reviews'23 Fashion dumps.

Streams the multi-GB JSONL files in a few passes and keeps only what the agents need:
a set of focus products (half suspicious, half random for contrast), all their reviews,
and the wider review history of every reviewer involved (for the reviewer graph).

Usage (from backend/):
    python -m scripts.build_dataset --reviews ../data/Amazon_Fashion.jsonl \
        --meta ../data/meta_Amazon_Fashion.jsonl --out ../data/trace.db
"""

import argparse
import html
import json
import random
import re
import sys
import time
from array import array
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.database import Database  # noqa: E402

DAY_MS = 86_400_000
_TAG = re.compile(r"<[^>]+>")


def clean(text: str | None, limit: int) -> str:
    return " ".join(_TAG.sub(" ", html.unescape(text or "")).split())[:limit]


def stream(path: Path) -> Iterator[dict]:
    with path.open("rb") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def unique_reviews(path: Path) -> Iterator[dict]:
    """The raw dump repeats a review once per product variant; keep one per (user, product, time)."""
    seen: set[int] = set()
    for r in stream(path):
        key = hash((r["user_id"], r["parent_asin"], r["timestamp"]))
        if key not in seen:
            seen.add(key)
            yield r


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def peak_window(days: list[int], width: int = 7) -> int:
    best, lo = 0, 0
    for hi, day in enumerate(days):
        while day - days[lo] >= width:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def profile_products(path: Path, min_reviews: int, max_reviews: int):
    days: dict[str, array] = defaultdict(lambda: array("i"))
    five, verified = defaultdict(int), defaultdict(int)
    totals = {"n": 0, "five": 0, "verified": 0}
    for r in unique_reviews(path):
        pid = r["parent_asin"]
        days[pid].append(r["timestamp"] // DAY_MS)
        is_five, is_ver = r["rating"] >= 5, bool(r.get("verified_purchase"))
        five[pid] += is_five
        verified[pid] += is_ver
        totals["n"] += 1
        totals["five"] += is_five
        totals["verified"] += is_ver
    log(f"pass 1: {totals['n']:,} reviews across {len(days):,} products")

    profiles = {}
    for pid, d in days.items():
        n = len(d)
        if not min_reviews <= n <= max_reviews:
            continue
        ordered = sorted(d)
        weeks = max(1.0, (ordered[-1] - ordered[0]) / 7)
        spike = peak_window(ordered) / max(n / weeks, 1.0)
        five_share, ver_share = five[pid] / n, verified[pid] / n
        suspicion = min(spike / 10, 1) * 0.6 + max(0.0, five_share - 0.6) + (1 - ver_share) * 0.2
        profiles[pid] = {"n": n, "spike": round(spike, 2), "suspicion": suspicion}

    baselines = {
        "five_star_share": totals["five"] / totals["n"],
        "verified_rate": totals["verified"] / totals["n"],
    }
    return profiles, baselines


def select_focus(profiles: dict, size: int, seed: int) -> set[str]:
    ranked = sorted(profiles, key=lambda p: profiles[p]["suspicion"], reverse=True)
    suspicious = ranked[: size // 2]
    rest = ranked[size // 2 :]
    random.Random(seed).shuffle(rest)
    return set(suspicious) | set(rest[: size - len(suspicious)])


def row(r: dict) -> tuple:
    return (
        r["parent_asin"],
        r["user_id"],
        float(r["rating"]),
        clean(r.get("title"), 300),
        clean(r.get("text"), 4000),
        int(r["timestamp"]),
        int(bool(r.get("verified_purchase"))),
        int(r.get("helpful_vote") or 0),
        int(bool(r.get("images"))),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", type=Path, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("../data/trace.db"))
    ap.add_argument("--focus", type=int, default=400, help="number of products to monitor")
    ap.add_argument("--min-reviews", type=int, default=30)
    ap.add_argument("--max-reviews", type=int, default=2500)
    ap.add_argument("--history-cap", type=int, default=40, help="max extra reviews kept per reviewer")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if args.out.exists():
        args.out.unlink()
    db = Database(args.out)
    db.init_schema()

    profiles, baselines = profile_products(args.reviews, args.min_reviews, args.max_reviews)
    focus = select_focus(profiles, args.focus, args.seed)
    log(f"selected {len(focus)} focus products from {len(profiles):,} candidates")

    focus_rows, users = [], set()
    for r in unique_reviews(args.reviews):
        if r["parent_asin"] in focus:
            focus_rows.append(row(r))
            users.add(r["user_id"])
    log(f"pass 2: {len(focus_rows):,} focus reviews by {len(users):,} reviewers")

    history_rows, kept = [], defaultdict(int)
    for r in unique_reviews(args.reviews):
        uid = r["user_id"]
        if uid in users and r["parent_asin"] not in focus and kept[uid] < args.history_cap:
            history_rows.append(row(r))
            kept[uid] += 1
    log(f"pass 3: {len(history_rows):,} reviewer-history reviews")

    counts: dict[str, int] = defaultdict(int)
    for rec in focus_rows + history_rows:
        counts[rec[0]] += 1

    products = []
    for m in stream(args.meta):
        pid = m.get("parent_asin")
        if pid not in counts:
            continue
        image = next((i.get("large") for i in m.get("images") or [] if i.get("large")), None)
        price = m.get("price")
        products.append(
            (
                pid,
                clean(m.get("title"), 300) or "Untitled product",
                m.get("store"),
                m.get("average_rating"),
                m.get("rating_number"),
                float(price) if isinstance(price, (int, float)) else None,
                image,
                json.dumps((m.get("features") or [])[:6]),
                counts[pid],
                profiles.get(pid, {}).get("spike", 0.0),
                int(pid in focus),
            )
        )
    known = {p[0] for p in products}
    products += [
        (
            pid,
            "Untitled product",
            None,
            None,
            None,
            None,
            None,
            "[]",
            n,
            profiles.get(pid, {}).get("spike", 0.0),
            int(pid in focus),
        )
        for pid, n in counts.items()
        if pid not in known
    ]
    log(f"meta pass: {len(products):,} products ({len(known):,} with metadata)")

    with db.connect() as conn:
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)", products)
        conn.executemany(
            "INSERT INTO reviews (product_id,user_id,rating,title,text,ts,verified,helpful,has_images) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            focus_rows + history_rows,
        )
        conn.executemany("INSERT INTO baselines VALUES (?,?)", baselines.items())
    log(f"done → {args.out}")


if __name__ == "__main__":
    main()

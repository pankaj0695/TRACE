import random

import pytest

from app.core.config import Settings
from app.data.database import Database

DAY = 86_400_000
T0 = 1_600_000_000_000
TEMPLATE = "Absolutely love it, exceeded my expectations and will buy again for sure"
WORDS = (
    "strap buckle zipper lining stitching pocket colour handle clasp seam leather canvas weight size "
    "commute travel office gift rain winter daughter wife husband summer beach laptop phone keys wallet"
).split()


def _seed(db: Database) -> None:
    rng = random.Random(0)
    products = [
        ("CLEAN", "Leather Crossbody Bag", "Honest Co", 4.2, 90, None, None, '["genuine leather strap"]', 60, 2.0, 1),
        ("SHADY", "Aria Crossbody Bag", "Shady Store", 4.9, 512, None, None, '["vegan leather"]', 60, 20.0, 1),
        ("SIDE1", "Shady Wallet", "Shady Store", 4.9, 40, None, None, "[]", 20, 0, 0),
        ("SIDE2", "Shady Belt", "Shady Store", 4.9, 40, None, None, "[]", 20, 0, 0),
    ]
    reviews = []
    for i in range(60):  # organic: spread over two years, varied text and ratings
        reviews.append(
            (
                "CLEAN",
                f"c{i}",
                float(rng.choice([2, 3, 4, 4, 5, 5])),
                "ok",
                " ".join(rng.sample(WORDS, 12)),
                T0 + i * 12 * DAY,
                1,
                0,
                0,
            )
        )
    for i in range(20):  # organic background for SHADY
        reviews.append(("SHADY", f"o{i}", 4.0, "fine", " ".join(rng.sample(WORDS, 12)), T0 + i * 30 * DAY, 1, 0, 0))
    for i in range(40):  # ring: burst of templated 5-star reviews by accounts that also review the same seller items
        ts = T0 + 400 * DAY + (i % 5) * DAY
        reviews.append(("SHADY", f"ring{i}", 5.0, "Five stars", TEMPLATE, ts, 0, 0, 0))
        reviews.append(("SIDE1", f"ring{i}", 5.0, "Great", TEMPLATE, ts + DAY, 0, 0, 0))
        reviews.append(("SIDE2", f"ring{i}", 5.0, "Great", TEMPLATE, ts + 2 * DAY, 0, 0, 0))
    with db.connect() as conn:
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?)", products)
        conn.executemany(
            "INSERT INTO reviews (product_id,user_id,rating,title,text,ts,verified,helpful,has_images) VALUES (?,?,?,?,?,?,?,?,?)",
            reviews,
        )
        conn.executemany("INSERT INTO baselines VALUES (?,?)", [("five_star_share", 0.57), ("verified_rate", 0.93)])


@pytest.fixture
def settings(tmp_path) -> Settings:
    db = Database(tmp_path / "trace.db")
    db.init_schema()
    _seed(db)
    return Settings(db_path=db.path, embedder="tfidf", gemini_api_key=None, graph_backend="networkx", approved_processors="")

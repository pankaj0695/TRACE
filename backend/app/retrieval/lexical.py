from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer

from app.retrieval.text import is_generic


@dataclass(frozen=True)
class Hit:
    review_id: int
    product_id: str
    score: float


class LexicalIndex:
    """TF-IDF inverted index over every review in the working set (fast recall stage of search)."""

    def __init__(self, rows: list[tuple[int, str, str, str]]):
        self.rebuild(rows)

    def rebuild(self, rows: list[tuple[int, str, str, str]]) -> None:
        """(Re)build in place so agents holding a reference see the new corpus (used after erasure)."""
        self.ids = np.array([r[0] for r in rows], dtype=np.int64)
        self.products = np.array([r[1] for r in rows], dtype=object)
        self.users = np.array([r[2] for r in rows], dtype=object)
        self.position = {rid: i for i, rid in enumerate(self.ids.tolist())}
        texts = [r[3] for r in rows]
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode")
        self.matrix: csr_matrix = self.vectorizer.fit_transform(texts)
        self.generic_share = float(np.mean([is_generic(t) for t in texts])) if texts else 0.0

    def __len__(self) -> int:
        return len(self.ids)

    def vectors(self, review_ids: list[int]) -> csr_matrix:
        return self.matrix[[self.position[r] for r in review_ids if r in self.position]]

    def search(self, query: str, k: int) -> list[Hit]:
        scores = (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()
        return self._top(scores, k)

    def cross_listing_matches(self, review_ids: list[int], product_id: str, threshold: float) -> list[tuple[int, Hit]]:
        """Reviews of `product_id` whose text reappears near-verbatim on other products under another account."""
        present = [r for r in review_ids if r in self.position]
        if not present:
            return []
        sims = (self.vectors(present) @ self.matrix.T).tocsr()
        matches = []
        for row, rid in enumerate(present):
            start, end = sims.indptr[row], sims.indptr[row + 1]
            cols, vals = sims.indices[start:end], sims.data[start:end]
            author = self.users[self.position[rid]]
            for col, val in zip(cols, vals, strict=False):
                if val >= threshold and self.products[col] != product_id and self.users[col] != author:
                    matches.append((rid, Hit(int(self.ids[col]), self.products[col], float(val))))
        return matches

    def _top(self, scores: np.ndarray, k: int) -> list[Hit]:
        k = min(k, len(scores))
        if k == 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [Hit(int(self.ids[i]), self.products[i], float(scores[i])) for i in top if scores[i] > 0]

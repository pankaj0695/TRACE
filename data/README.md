# data/

Nothing in this folder except this file is committed to Git (see the root `.gitignore`). It holds:

| File | What | Why it is not in the repo |
| --- | --- | --- |
| `Amazon_Fashion.jsonl` | Raw review dump (~1 GB) | Too large for GitHub; third-party dataset with its own licence |
| `meta_Amazon_Fashion.jsonl` | Raw product metadata (~1.4 GB) | Same |
| `trace.db` | Working set built from the dumps: reviews (text + reviewer ids), analyses, audit log, egress ledger | Contains user-generated content and pseudonymous identifiers; generated, so reproducible |
| `erasure_suppression.txt` | SHA-256 hashes of data subjects who requested erasure | Compliance record; keep it with the database, not in source control |

## Get the data

Download **Amazon Reviews 2023 -> Fashion** (reviews + metadata, JSONL) from the McAuley Lab dataset page
(<https://amazon-reviews-2023.github.io/>), check its licence terms, and place the two files here.

## Build `trace.db`

```bash
cd backend
python -m scripts.build_dataset --reviews ../data/Amazon_Fashion.jsonl --meta ../data/meta_Amazon_Fashion.jsonl
```

The builder honours `erasure_suppression.txt`, so erased subjects are never re-ingested.
The backend also looks for `trace.db` in `TRACE_DATA_DIR` or `backend/data` (see the main README).

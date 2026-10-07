# TRACE — Trust & Review Authenticity Classifier for E-commerce

A multi-agent trust-and-safety console for Amazon Fashion listings (PS-11 + PS-13). Six LangGraph agents
analyse a listing's reviews, reviewer graph and language, then an orchestrator drafts a policy-mapped report
for a human reviewer with Gemini (Interactions API). TRACE flags and explains; it never enforces.

```
ingestion ──► anomaly ───────┐
          ├─► authenticity ──┼─► trust scoring ──► orchestrator (Gemini report)
          └─► network ───────┘
```

| Subject              | Where it lives                                                                                                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agentic AI           | `backend/app/agents/*`, `backend/app/pipeline/graph.py` — LangGraph state graph, conditional routing, parallel fan-out, fault-isolated agents, LLM report with rule-based fallback                                                         |
| Knowledge Graph & IR | `backend/app/graph/store.py` — Reviewer–Product–Store graph (NetworkX or Neo4j/Cypher), co-review rings; `backend/app/retrieval/*` — TF-IDF index + MiniLM embeddings for near-duplicates, cross-listing copies and semantic review search |

## Run it

**1. Backend** (Python 3.10+)

```bash
cd backend
python -m venv .venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GEMINI_API_KEY (optional — rules-only reports without it)

# one-off: build the working set from the raw dumps in ../data (~1 min)
python -m scripts.build_dataset --reviews ../data/Amazon_Fashion.jsonl --meta ../data/meta_Amazon_Fashion.jsonl

python -m scripts.scan_all --limit 100   # optional: pre-populate the console (no LLM calls)
uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (Node 20+)

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

**Optional — Neo4j** instead of the in-process graph:

```bash
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/trace-password neo4j:5
# then set TRACE_GRAPH_BACKEND=neo4j in backend/.env — the graph is loaded on first start
```

If Neo4j or Gemini is unreachable the app falls back to NetworkX / rule-based reports instead of failing.

## Tests

```bash
cd backend && pytest -q
cd frontend && npm run lint && npm run build
```

## API

| Method | Path                                          | Purpose                                                    |
| ------ | --------------------------------------------- | ---------------------------------------------------------- |
| GET    | `/api/health`                                 | Active graph backend, embedder, LLM                        |
| GET    | `/api/stats`                                  | Console KPIs                                               |
| GET    | `/api/products?q=&tier=&sort=&limit=&offset=` | Monitored listings with latest scan                        |
| GET    | `/api/products/{id}/analysis/stream`          | Run the pipeline (Server-Sent Events per agent)            |
| GET    | `/api/products/{id}/analysis`                 | Latest saved analysis                                      |
| GET    | `/api/search/reviews?q=`                      | Semantic review search (TF-IDF recall → embedding re-rank) |
| GET    | `/api/analyses/export.csv`                    | Audit export                                               |

## Data notes

The dataset has no IP, device or account-creation fields, so the network agent uses proxies available in
the data: co-review overlap, seller concentration, and each reviewer's first review in the dataset.

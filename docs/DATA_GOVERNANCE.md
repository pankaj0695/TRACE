# TRACE - Data governance for an enterprise agent system

Scope: how TRACE (a LangGraph multi-agent system with an LLM report writer and an MCP interface) collects, uses,
shares, retains and disposes of data. The rules are **code**, in `backend/app/governance/policy.py`, and are
enforced at the points listed below. Tests in `backend/tests/test_data_governance.py` prove each control.

## 1. Data inventory and classification

Four levels: `public`, `internal`, `confidential`, `restricted`. Every column of every table is classified in the
catalogue (owner, source, purpose, legal basis, retention, personal-data category). A test fails if a column is added
without being classified; the `data_catalogue_covers_schema` quality check does the same at runtime.

| Data | Classification | Personal data |
| --- | --- | --- |
| Listing metadata (`products`), baselines, scores, tiers | internal | none |
| Review text/title, reviewer id, review timestamps (`reviews`) | confidential | pseudonymous identifier, user-generated content |
| Saved analyses (`analyses.payload`), reviewer decisions | confidential | pseudonymous ids, staff identifiers, free text |
| Audit log, egress ledger, erasure register, governance secrets | restricted | staff identifiers, request metadata |

**Classification-based access.** Each MCP role has a clearance: viewer = internal, analyst/reviewer = confidential,
admin = restricted. Tools and resources carry a classification; a caller can neither see nor call anything above their
clearance. Every tool result carries `_meta` (`trace/classification`, `trace/purpose`, `trace/policy_version`).

## 2. Purpose limitation and minimisation

* Declared purposes: `abuse_detection` (primary), `abuse_investigation`, `policy_review`, `quality_assurance`,
  `reviewer_report_drafting`, `data_subject_request`, `audit_and_compliance`.
* Access to raw review text (`search_reviews`) and reviewer-level evidence (`get_analysis detail=full`) **requires a
  declared `purpose`**, which is validated and written to the audit trail with the call.
* Viewers receive summaries only (no per-account evidence, no review text). UI-only artifacts never leave the server.
* The dataset has no names, IPs or devices; the network agent uses co-review overlap and first-review dates instead.
* Emails, phone numbers, key-like strings and control/bidi characters are redacted from every MCP output.

## 3. Lineage and provenance

Every saved analysis includes `lineage`: dataset version (content-derived fingerprint), counts of inputs, the product's
input-quality result, each agent's status and duration, who wrote the report (`rules` or the LLM model), which
third-party processors were involved, approved processors at the time, policy version, classification, purpose and
retention. Reviewers and auditors can therefore answer "what data and which models produced this verdict?".

## 4. Third-party processors and cross-border flow

Nothing leaves the machine unless the processor is listed in `TRACE_APPROVED_PROCESSORS`. **Prototype default: `gemini,neo4j`** (pre-approved for demo convenience; the minimisation and ledger controls below still apply). **Production target: local LLM + local database, with the setting empty**, which blocks all external flows by policy.

| Processor | What it would receive | Control |
| --- | --- | --- |
| Google Gemini (report drafting) | aggregated detector evidence, listing title/store, policy findings | approval gate -> reviewer ids pseudonymised (keyed HMAC) -> PII/secrets redacted -> size cap -> **ledger row (hash, size, redactions; never the content)** written before the call, call withheld if the ledger fails -> model output scrubbed |
| Hosted Neo4j (Aura) | pseudonymous reviewer id, product, store, rating, timestamp per review | blocked and replaced by the in-process graph unless approved (approved in the prototype); local/Docker Neo4j is not a third party |

`TRACE_LLM_EGRESS_MODE=off` disables LLM egress entirely. Without approval the system degrades gracefully to rule-based
reports. Before approving a processor complete a data-protection review: data residency, retention at the processor,
use of data for training, and a signed DPA.

## 5. Data quality

`get_data_quality_report` / `python -m scripts.governance quality` check referential integrity, rating and timestamp
ranges, empty text, duplicate rows, baselines, PII candidates and catalogue coverage. Per-analysis input checks
(out-of-range ratings, empty-text share, future dates, missing baselines) are stored in the lineage and surfaced as
warnings. Reviewers should treat results with quality warnings as lower confidence.

## 6. Retention and disposal

| Data | Default retention | Setting |
| --- | --- | --- |
| Saved analyses | 365 days | `TRACE_RETENTION_ANALYSES_DAYS` |
| LLM egress ledger | 180 days | `TRACE_RETENTION_EGRESS_DAYS` |
| Reviewer decisions | 1095 days | `TRACE_RETENTION_DECISIONS_DAYS` |
| MCP audit log | 730 days | `TRACE_RETENTION_AUDIT_DAYS` |
| Source reviews | until dataset rebuild or erasure | - |

`run_retention_purge` (admin; dry-run by default, `confirm=true` to execute) or
`python -m scripts.governance retention [--execute]`. Audit rows are append-only (SQL triggers); expired rows are only
deletable by the retention routine, which removes a contiguous expired prefix and leaves a **hash checkpoint** so
`verify_audit_chain` still proves integrity of the remainder. Schedule it (cron / Task Scheduler).

## 7. Data-subject rights (GDPR Art. 15/17, DPDP Act 2023 ss. 11-13)

* **Access:** `export_subject_data(user_id, reference)` returns what TRACE holds for a reviewer id.
* **Erasure:** `erase_subject_data(user_id, reference, dry_run, confirm)` deletes the subject's reviews, removes graph
  edges, rebuilds the text index, invalidates saved analyses that embed the subject, updates counts and dataset version,
  registers the request (subject stored only as a SHA-256 hash) and appends the hash to
  `data/erasure_suppression.txt`, which `build_dataset` honours so rebuilds never re-ingest the subject.
* Both are admin-only, ticket-referenced, audited, and dry-run by default. Identity verification of the requester is a
  process step outside the system (the dataset's ids are pseudonymous and cannot be linked to a person by TRACE).

## 8. Human oversight, accountability and AI-specific controls

TRACE recommends; humans decide (see `MCP_AND_GOVERNANCE.md` s.3). Only `reviewer`/`admin` roles can record a decision,
with rationale and confirmation. Reports carry `human_review_required`, detector-conflict flags and the reviewer note.
LLM output is validated against a schema, scrubbed, and never used to take action. Review text is labelled untrusted.

## 9. Records of processing (summary for the DPO)

| Item | Entry |
| --- | --- |
| Controller / owner | Trust & Safety data owner (set your organisation's name here) |
| Purpose | Detecting review manipulation and coordinated inauthentic behaviour on marketplace listings |
| Legal basis (indicative) | Legitimate interest / legitimate use for fraud and abuse prevention - confirm with counsel |
| Data subjects | Marketplace reviewers (pseudonymous), TRACE staff users |
| Recipients | Approved processors only (Section 4) |
| Retention | Section 6 |
| Security | Role-based access, clearance levels, redaction, tamper-evident audit, rate limits, fail-closed logging |
| Source licence | Amazon Reviews'23 (McAuley Lab) - **verify licence terms before any production/commercial use** |

## 10. Known gaps / your organisation's to-dos

* The REST API used by the React console (`/api/*`) has **no authentication** and exposes review text through
  `/api/search/reviews`. Put it behind SSO/a reverse proxy, or bind to localhost, before any shared deployment.
* Review text in the source data contains some emails/phone numbers (see the quality report). They are redacted on MCP
  output and before LLM egress, but not removed from the database; cleanse at build time for stronger minimisation.
* Encryption at rest (SQLite file / disk), backup retention and a breach-notification runbook are infrastructure
  responsibilities not implemented here. A hash-chained log makes tampering evident; it does not prevent a database
  administrator from rewriting everything.
* Prototype exception: Gemini and hosted Neo4j are pre-approved. A DPIA and processor DPAs are needed before real data goes to them; the production plan (local LLM and database) removes the need.
* Sessions/rate-limit state are per-process (single worker assumed).

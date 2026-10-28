"""Data governance policy as code: classification scheme, data catalogue, purposes, retention, processors.

This is the single source of truth. Enforcement points read from here (MCP clearance checks, the LLM egress guard,
retention jobs, subject-rights handlers), `docs/DATA_GOVERNANCE.md` describes it, and a test fails when a database
column is added without being classified, so the catalogue cannot silently drift from the schema.
"""

POLICY_VERSION = "1.0"

# ---- classification ------------------------------------------------------------------------------------------
CLASSES = ("public", "internal", "confidential", "restricted")
CLASS_RANK = {c: i for i, c in enumerate(CLASSES)}
CLASS_HANDLING = {
    "public": "No restrictions.",
    "internal": "Authenticated staff and agents; aggregate or non-personal business data.",
    "confidential": "Role-limited; contains user-generated content or pseudonymous identifiers; redact before external sharing.",
    "restricted": "Admin only; personal-data operations, security records and anything that can identify a data subject's activity.",
}
# Highest classification each MCP role may receive (data-classification-based access control).
ROLE_CLEARANCE = {"viewer": "internal", "analyst": "confidential", "reviewer": "confidential", "admin": "restricted"}

# ---- purposes (purpose limitation) ---------------------------------------------------------------------------
PURPOSES = {
    "abuse_detection": "Detect and explain review manipulation on marketplace listings (primary purpose).",
    "abuse_investigation": "A reviewer/analyst examines specific evidence behind a flagged listing.",
    "policy_review": "Check findings against marketplace policy before a human decision.",
    "quality_assurance": "Validate detector behaviour and data quality.",
    "reviewer_report_drafting": "Draft the reviewer brief with an LLM from minimised evidence.",
    "data_subject_request": "Fulfil an access/erasure request from a data subject (ticket reference required).",
    "audit_and_compliance": "Operate the audit trail, retention and governance controls.",
}
INVESTIGATION_PURPOSES = ("abuse_investigation", "policy_review", "quality_assurance", "data_subject_request")

# ---- retention (days). None = until superseded or erased ------------------------------------------------------
RETENTION_DEFAULT_DAYS = {"analyses": 365, "llm_egress_ledger": 180, "reviewer_decisions": 1095, "mcp_audit": 730}

# ---- third-party processors ----------------------------------------------------------------------------------
PROCESSORS = {
    "gemini": {
        "name": "Google Gemini API (Interactions)",
        "purpose": "reviewer_report_drafting",
        "data_sent": "Aggregated detector evidence, listing title/store, policy findings. Reviewer ids are pseudonymised, "
        "emails/phones/secrets are redacted before sending.",
        "region": "Determined by Google; verify data-residency terms before enterprise use.",
        "requires_approval": True,
    },
    "neo4j": {
        "name": "Neo4j (when pointed at a hosted/Aura instance)",
        "purpose": "abuse_detection",
        "data_sent": "Pseudonymous reviewer id, product id, store, rating, timestamp for every review edge.",
        "region": "Per Neo4j Aura region; local/Docker instances are not third-party processors.",
        "requires_approval": True,
    },
}

# ---- catalogue -------------------------------------------------------------------------------------------------
# column -> (classification, personal-data category or None)
_ID, _N = "internal", None
CATALOG: dict[str, dict] = {
    "products": {
        "description": "Marketplace listing metadata from the Amazon Reviews 2023 (Fashion) dump.",
        "owner": "Trust & Safety data owner",
        "source": "Amazon Reviews'23, McAuley Lab (third-party public dataset; check licence terms for production use)",
        "purpose": "abuse_detection",
        "legal_basis": "Legitimate use: fraud and abuse prevention",
        "retention": "Until the dataset is rebuilt",
        "columns": {
            "id": (_ID, _N), "title": (_ID, _N), "store": (_ID, "business_name"), "avg_rating": (_ID, _N),
            "rating_count": (_ID, _N), "price": (_ID, _N), "image_url": (_ID, _N), "features": (_ID, _N),
            "review_count": (_ID, _N), "spike_ratio": (_ID, _N), "is_focus": (_ID, _N),
        },
    },
    "reviews": {
        "description": "Public product reviews plus the wider history of reviewers involved in monitored listings.",
        "owner": "Trust & Safety data owner",
        "source": "Amazon Reviews'23 (pseudonymous reviewer ids; no names, IPs or devices)",
        "purpose": "abuse_detection",
        "legal_basis": "Legitimate use: fraud and abuse prevention; subject to erasure requests",
        "retention": "Until the dataset is rebuilt or the subject is erased",
        "columns": {
            "id": (_ID, _N), "product_id": (_ID, _N), "user_id": ("confidential", "pseudonymous_identifier"),
            "rating": (_ID, _N), "title": ("confidential", "user_generated_content"),
            "text": ("confidential", "user_generated_content"), "ts": ("confidential", "behavioural_timestamp"),
            "verified": (_ID, _N), "helpful": (_ID, _N), "has_images": (_ID, _N),
        },
    },
    "baselines": {
        "description": "Corpus-wide reference rates used by the anomaly agent.",
        "owner": "Trust & Safety data owner", "source": "Derived from reviews", "purpose": "abuse_detection",
        "legal_basis": "Aggregate statistics", "retention": "Until the dataset is rebuilt",
        "columns": {"key": (_ID, _N), "value": (_ID, _N)},
    },
    "analyses": {
        "description": "Saved multi-agent analyses with lineage, evidence and the policy-mapped report.",
        "owner": "Trust & Safety data owner", "source": "Generated by TRACE agents", "purpose": "abuse_detection",
        "legal_basis": "Legitimate use: fraud and abuse prevention",
        "retention": f"{RETENTION_DEFAULT_DAYS['analyses']} days",
        "columns": {
            "product_id": (_ID, _N), "risk_score": (_ID, _N), "tier": (_ID, _N), "created_at": (_ID, _N),
            "payload": ("confidential", "pseudonymous_identifier"),
        },
    },
    "reviewer_decisions": {
        "description": "Human decisions on flagged listings, with rationale and decider identity.",
        "owner": "Trust & Safety lead", "source": "Reviewers", "purpose": "policy_review",
        "legal_basis": "Accountability and records of human oversight",
        "retention": f"{RETENTION_DEFAULT_DAYS['reviewer_decisions']} days",
        "columns": {
            "id": (_ID, _N), "product_id": (_ID, _N), "decision": (_ID, _N), "rationale": ("confidential", "free_text"),
            "principal": ("confidential", "staff_identifier"), "role": (_ID, _N), "session_id": ("confidential", _N),
            "analysis_created_at": (_ID, _N), "risk_score": (_ID, _N), "tier": (_ID, _N), "created_at": (_ID, _N),
        },
    },
    "mcp_audit": {
        "description": "Tamper-evident audit trail of every MCP request.",
        "owner": "Security / compliance", "source": "MCP server", "purpose": "audit_and_compliance",
        "legal_basis": "Legal obligation and legitimate interest (security, accountability)",
        "retention": f"{RETENTION_DEFAULT_DAYS['mcp_audit']} days (purged only through the checkpointed retention routine)",
        "columns": {
            "id": ("restricted", _N), "ts": ("restricted", _N), "session_id": ("restricted", _N),
            "principal": ("restricted", "staff_identifier"), "role": ("restricted", _N), "transport": ("restricted", _N),
            "method": ("restricted", _N), "target": ("restricted", _N), "args": ("restricted", "redacted_request_args"),
            "outcome": ("restricted", _N), "detail": ("restricted", _N), "duration_ms": ("restricted", _N),
            "prev_hash": ("restricted", _N), "hash": ("restricted", _N),
        },
    },
    "mcp_audit_checkpoint": {
        "description": "Hash anchor left behind when old audit rows are purged so the chain stays verifiable.",
        "owner": "Security / compliance", "source": "Retention routine", "purpose": "audit_and_compliance",
        "legal_basis": "Integrity of the audit trail", "retention": "Permanent",
        "columns": {k: ("restricted", _N) for k in ("id", "last_purged_id", "last_hash", "purged_at")},
    },
    "audit_purge_gate": {
        "description": "Transient flag that lets the retention routine (only) delete audit rows.",
        "owner": "Security / compliance", "source": "Retention routine", "purpose": "audit_and_compliance",
        "legal_basis": "Integrity of the audit trail", "retention": "Empty except during a purge",
        "columns": {"opened_at": ("restricted", _N)},
    },
    "llm_egress_ledger": {
        "description": "Record of every payload sent to an external LLM (hash, size, data classes, redactions - never the content).",
        "owner": "Security / compliance", "source": "LLM egress guard", "purpose": "audit_and_compliance",
        "legal_basis": "Accountability for third-party processing",
        "retention": f"{RETENTION_DEFAULT_DAYS['llm_egress_ledger']} days",
        "columns": {k: ("restricted", _N) for k in (
            "id", "ts", "processor", "model", "purpose", "data_classes", "bytes_sent", "redactions", "payload_sha256",
            "outcome", "detail")},
    },
    "erasure_requests": {
        "description": "Register of data-subject erasure requests (subject stored only as a SHA-256 hash).",
        "owner": "Data protection officer", "source": "Subject-rights handler", "purpose": "data_subject_request",
        "legal_basis": "Legal obligation (erasure right)", "retention": "Permanent (suppression list)",
        "columns": {k: ("restricted", _N) for k in (
            "id", "subject_hash", "reference", "requested_by", "reviews_deleted", "analyses_invalidated", "created_at")},
    },
    "governance_meta": {
        "description": "Governance settings such as the pseudonymisation salt.",
        "owner": "Security / compliance", "source": "System", "purpose": "audit_and_compliance",
        "legal_basis": "Security control", "retention": "Permanent",
        "columns": {"key": ("restricted", _N), "value": ("restricted", _N)},
    },
}
# SQLite internal bookkeeping tables are not part of the catalogue.
IGNORED_TABLES = {"sqlite_sequence"}


def max_class(*names: str) -> str:
    return max(names, key=CLASS_RANK.__getitem__)


def table_classification(table: str) -> str:
    return max_class(*(c for c, _ in CATALOG[table]["columns"].values()))


def catalog_view() -> list[dict]:
    out = []
    for table, spec in CATALOG.items():
        cols = spec["columns"]
        out.append(
            {
                "table": table,
                **{k: v for k, v in spec.items() if k != "columns"},
                "classification": table_classification(table),
                "columns": {c: {"classification": cl, "personal_data": pii} for c, (cl, pii) in cols.items()},
            }
        )
    return out


def catalog_gaps(schema: dict[str, list[str]]) -> dict[str, list[str]]:
    """Tables/columns present in the database but missing from the catalogue (empty dict == compliant)."""
    gaps: dict[str, list[str]] = {}
    for table, columns in schema.items():
        if table in IGNORED_TABLES:
            continue
        known = CATALOG.get(table, {}).get("columns", {})
        missing = [c for c in columns if c not in known] if table in CATALOG else ["<table not catalogued>", *columns]
        if missing:
            gaps[table] = missing
    return gaps


def data_policy(settings) -> dict:
    """Machine-readable data-governance policy served to clients and auditors."""
    return {
        "version": POLICY_VERSION,
        "classification_scheme": {c: CLASS_HANDLING[c] for c in CLASSES},
        "role_clearance": ROLE_CLEARANCE,
        "purposes": PURPOSES,
        "retention_days": retention_days(settings),
        "third_party_processors": {
            k: {**v, "approved": k in approved_processors(settings)} for k, v in PROCESSORS.items()
        },
        "llm_egress": {
            "mode": settings.llm_egress_mode,
            "max_prompt_chars": settings.llm_max_prompt_chars,
            "controls": ["processor must be approved", "reviewer ids pseudonymised", "emails/phones/secrets redacted",
                         "payload hash + size logged, content never stored", "model output scrubbed before use"],
        },
        "data_subject_rights": "Access/export and erasure via admin tools; erasures are registered and suppressed on rebuild.",
        "principles": [
            "Collect and keep only what detection needs (minimisation).",
            "Use data only for declared purposes; investigation access requires a stated purpose.",
            "Classify everything; release data only to roles cleared for its classification.",
            "Every analysis carries lineage: dataset version, agents, quality checks, processors used.",
            "Retain for a defined period, then dispose; personal-data erasure is honoured end to end.",
            "No personal data leaves the system to a third party that has not been approved.",
        ],
    }


def approved_processors(settings) -> set[str]:
    return {p.strip().lower() for p in settings.approved_processors.split(",") if p.strip()}


def retention_days(settings) -> dict[str, int]:
    return {
        "analyses": settings.retention_analyses_days,
        "llm_egress_ledger": settings.retention_egress_days,
        "reviewer_decisions": settings.retention_decisions_days,
        "mcp_audit": settings.retention_audit_days,
    }

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.container import build_container
from app.governance.egress import GovernedLLM
from app.governance.policy import CATALOG, ROLE_CLEARANCE, catalog_gaps
from app.governance.quality import schema_of
from app.llm.client import LLMUnavailable
from app.main import create_app
from app.mcp.store import AuditEntry, AuditStore, _digest
from tests.test_mcp import ADMIN, ANALYST, KEYS, REVIEWER, VIEWER, call, open_session, rpc, text

REVIEWER_ID = "AE2ABCDEFGHIJKLMNOPQRSTUVWXY"  # shaped like an Amazon reviewer id


@pytest.fixture
def container(settings):
    c = build_container(settings)
    yield c
    c.close()


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings.model_copy(update={"mcp_api_keys": KEYS}))) as c:
        yield c


def old(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ---- catalogue / classification ---------------------------------------------------------------------------
def test_every_column_is_classified(container):
    assert catalog_gaps(schema_of(container.db)) == {}
    assert set(ROLE_CLEARANCE.values()) <= {"public", "internal", "confidential", "restricted"}


def test_catalog_gap_detection():
    gaps = catalog_gaps({"reviews": ["id", "new_sensitive_column"], "mystery": ["a"]})
    assert gaps["reviews"] == ["new_sensitive_column"] and "<table not catalogued>" in gaps["mystery"]
    assert all(spec["columns"] for spec in CATALOG.values())


def test_clearance_hides_and_blocks_restricted_tools(client):
    vsid, _ = open_session(client, VIEWER)
    listing = rpc(client, VIEWER, "tools/list", session=vsid).json()["result"]["tools"]
    assert "erase_subject_data" not in {t["name"] for t in listing}
    asid, _ = open_session(client, ANALYST)
    denied = call(client, ANALYST, asid, "get_egress_ledger").json()["result"]
    assert denied["isError"] and "may not call" in denied["content"][0]["text"]
    ok = call(client, ANALYST, asid, "get_data_catalog").json()["result"]
    assert ok["_meta"]["trace/classification"] == "internal"
    tools = {t["name"]: t for t in rpc(client, ADMIN, "tools/list", session=open_session(client, ADMIN)[0]).json()["result"]["tools"]}
    assert tools["erase_subject_data"]["annotations"]["destructiveHint"] is True
    assert tools["erase_subject_data"]["_meta"]["trace/classification"] == "restricted"


def test_result_classification_rises_with_detail(client):
    sid, _ = open_session(client, ANALYST)
    call(client, ANALYST, sid, "run_analysis", {"product_id": "SHADY"})
    full = call(client, ANALYST, sid, "get_analysis", {"product_id": "SHADY", "detail": "full", "purpose": "policy_review"}).json()["result"]
    assert full["_meta"]["trace/classification"] == "confidential" and full["_meta"]["trace/purpose"] == "policy_review"
    summary = call(client, ANALYST, sid, "get_analysis", {"product_id": "SHADY"}).json()["result"]
    assert summary["_meta"]["trace/classification"] == "internal"


# ---- purpose limitation -----------------------------------------------------------------------------------
def test_investigation_access_requires_declared_purpose(client):
    sid, _ = open_session(client, ANALYST)
    call(client, ANALYST, sid, "run_analysis", {"product_id": "SHADY"})
    missing = call(client, ANALYST, sid, "get_analysis", {"product_id": "SHADY", "detail": "full"}).json()["result"]
    assert missing["isError"] and "purpose" in missing["content"][0]["text"]
    assert call(client, ANALYST, sid, "search_reviews", {"query": "great"}).json()["error"]["code"] == -32602
    assert call(client, ANALYST, sid, "search_reviews", {"query": "great", "purpose": "marketing"}).json()["error"]["code"] == -32602
    ok = call(client, ANALYST, sid, "search_reviews", {"query": "great", "purpose": "abuse_investigation"}).json()["result"]
    assert ok["isError"] is False and ok["_meta"]["trace/purpose"] == "abuse_investigation"
    asid, _ = open_session(client, ADMIN)
    entries = text(call(client, ADMIN, asid, "get_audit_log", {"limit": 50}))["entries"]
    assert any("purpose=abuse_investigation" in (e["detail"] or "") for e in entries)  # purpose is on the audit record


# ---- lineage & quality ------------------------------------------------------------------------------------
def test_analysis_carries_lineage(container):
    a = asyncio.run(container.analysis.run("SHADY"))
    lin = a.lineage
    assert lin["dataset"]["version"] and lin["dataset"]["reviews"] > 0
    assert lin["quality"]["status"] in ("pass", "warn") and lin["inputs"]["reviews"] == 60
    assert lin["third_party_processors"] == [] and lin["governance"]["classification"] == "confidential"
    assert set(lin["agents"]) >= {"ingestion", "anomaly", "authenticity", "network", "scoring", "orchestrator"}
    assert container.analysis.latest("SHADY").lineage == lin  # persisted with the analysis


def test_dataset_version_changes_when_data_changes(container):
    before = container.governance.dataset["version"]
    with container.db.connect() as conn:
        conn.execute("DELETE FROM reviews WHERE user_id='c0'")
    container.governance.refresh_dataset()
    assert container.governance.dataset["version"] != before


def test_quality_report_passes_on_clean_data_and_flags_problems(container):
    report = container.governance.quality.report()
    assert report["overall"] in ("pass", "warn") and not [c for c in report["checks"] if c["status"] == "fail"]
    with container.db.connect() as conn:
        conn.execute("UPDATE reviews SET rating = 9 WHERE id = 1")
        conn.execute("UPDATE reviews SET text = 'mail jo@example.com' WHERE id = 2")
    bad = {c["check"]: c["status"] for c in container.governance.quality.report()["checks"]}
    assert bad["rating_range_1_to_5"] == "fail" and bad["pii_candidates_in_review_text"] == "warn"


# ---- LLM egress governance ---------------------------------------------------------------------------------
class Recorder:
    name = "rec-model"

    def __init__(self):
        self.seen = []

    async def generate_json(self, system, prompt, schema):
        self.seen.append(prompt)
        return {"headline": "Contact boss@corp.com", "summary": "s"}


def governed(container, **overrides):
    s = container.settings.model_copy(update=overrides)
    inner = Recorder()
    return inner, GovernedLLM(inner, s, container.governance.pseudonyms, container.governance.ledger)


def test_unapproved_processor_is_blocked_and_logged(container):
    inner, llm = governed(container, approved_processors="")
    with pytest.raises(LLMUnavailable, match="not approved"):
        asyncio.run(llm.generate_json("sys", "prompt", {}))
    assert inner.seen == []
    assert container.governance.ledger.tail(1)[0]["outcome"] == "blocked"


def test_egress_off_mode_blocks_even_approved(container):
    inner, llm = governed(container, approved_processors="gemini", llm_egress_mode="off")
    with pytest.raises(LLMUnavailable, match="off"):
        asyncio.run(llm.generate_json("sys", "p", {}))


def test_approved_egress_is_minimised_logged_and_output_scrubbed(container):
    inner, llm = governed(container, approved_processors="gemini", llm_max_prompt_chars=400)
    prompt = f"Reviewer {REVIEWER_ID} wrote to a@b.com / +1 415 555 0100 key " + "AI" + "za" + "SyFAKEFAKEFAKEFAKE0123456789 " + "x" * 800
    out = asyncio.run(llm.generate_json("system", prompt, {}))
    sent = inner.seen[0]
    assert REVIEWER_ID not in sent and "a@b.com" not in sent and "415 555" not in sent and "AIza" not in sent
    assert "reviewer-" in sent and "truncated by data-minimisation" in sent and len(sent) < 600
    assert "boss@corp.com" not in json.dumps(out)
    row = container.governance.ledger.tail(1)[0]
    assert row["outcome"] == "sent" and row["redactions"] >= 4 and len(row["payload_sha256"]) == 64
    assert sent not in json.dumps(row)  # ledger never stores content


def test_pseudonyms_are_stable_and_distinct(container):
    p = container.governance.pseudonyms
    assert p.token("AAA") == p.token("AAA") != p.token("AAB")


def test_llm_configured_but_unapproved_falls_back_to_rules(settings):
    c = build_container(settings.model_copy(update={"gemini_api_key": "fake-key-not-used", "approved_processors": ""}))
    a = asyncio.run(c.analysis.run("SHADY"))
    assert a.report.generated_by == "rules" and a.lineage["third_party_processors"] == []
    assert c.governance.ledger.summary()["blocked"]["calls"] >= 1
    c.close()


def test_hosted_neo4j_requires_approval(settings):
    s = settings.model_copy(update={"graph_backend": "neo4j", "neo4j_uri": "neo4j+s://abc.databases.neo4j.io"})
    c = build_container(s)
    assert c.graph.name == "networkx"
    c.close()


# ---- retention ---------------------------------------------------------------------------------------------
def test_retention_dry_run_then_purge_with_audit_checkpoint(client):
    c = client.app.state.container
    asyncio.run(c.analysis.run("SHADY"))
    with c.db.connect() as conn:
        conn.execute("UPDATE analyses SET created_at = ?", (old(400),))
        conn.execute("INSERT INTO llm_egress_ledger (ts, processor, purpose, data_classes, bytes_sent, redactions, payload_sha256, outcome) VALUES (?,?,?,?,?,?,?,?)",
                     (old(400), "gemini", "reviewer_report_drafting", "internal", 1, 0, "h", "sent"))
    store = AuditStore(c.db)
    for i in range(3):  # three audit rows older than the audit retention window
        e = AuditEntry(None, "ghost", "admin", "http", "tools/call", f"old{i}", None, "ok")
        ts = old(900)
        with c.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prev = (conn.execute("SELECT hash FROM mcp_audit ORDER BY id DESC LIMIT 1").fetchone() or ["0" * 64])[0]
            conn.execute("INSERT INTO mcp_audit (ts,session_id,principal,role,transport,method,target,args,outcome,detail,duration_ms,prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (*store._fields(ts, e), prev, _digest(prev, store._fields(ts, e))))
    asid, _ = open_session(client, ADMIN)  # recent audit rows are written after the expired ones
    dry = text(call(client, ADMIN, asid, "run_retention_purge", {}))
    assert dry["dry_run"] and dry["tables"]["analyses"]["expired_rows"] == 1 and dry["tables"]["analyses"]["deleted"] == 0
    assert dry["tables"]["mcp_audit"]["expired_rows"] == 3
    refused = call(client, ADMIN, asid, "run_retention_purge", {"dry_run": False}).json()["result"]
    assert refused["isError"]  # needs confirm
    done = text(call(client, ADMIN, asid, "run_retention_purge", {"dry_run": False, "confirm": True}))
    assert done["tables"]["analyses"]["deleted"] == 1 and done["tables"]["llm_egress_ledger"]["deleted"] == 1
    assert done["tables"]["mcp_audit"]["deleted"] == 3
    assert c.analysis.latest("SHADY") is None
    verify = text(call(client, ADMIN, asid, "verify_audit_chain"))
    assert verify["intact"] is True and verify["checkpoint_id"]  # chain resumes from the checkpoint


def test_audit_rows_cannot_be_deleted_outside_retention(container):
    AuditStore(container.db).record(AuditEntry(None, "p", "viewer", "http", "ping", None, None, "ok"))
    with pytest.raises(Exception, match="append-only"):
        with container.db.connect() as conn:
            conn.execute("DELETE FROM mcp_audit")


# ---- data-subject rights -------------------------------------------------------------------------------------
def test_subject_access_and_erasure_end_to_end(client, settings):
    c = client.app.state.container
    asyncio.run(c.analysis.run("SHADY"))
    sid, _ = open_session(client, ADMIN)
    args = {"user_id": "ring0", "reference": "DSR-2026-001"}
    export = text(call(client, ADMIN, sid, "export_subject_data", args))
    assert export["review_count"] == 3 and export["reference"] == "DSR-2026-001"

    preview = text(call(client, ADMIN, sid, "erase_subject_data", args))
    assert preview["dry_run"] and preview["reviews_to_delete"] == 3
    assert text(call(client, ADMIN, sid, "export_subject_data", args))["review_count"] == 3  # nothing changed
    assert call(client, ADMIN, sid, "erase_subject_data", {**args, "dry_run": False}).json()["result"]["isError"]

    done = text(call(client, ADMIN, sid, "erase_subject_data", {**args, "dry_run": False, "confirm": True}))
    assert done["reviews_deleted"] == 3 and done["analyses_invalidated"] >= 1
    assert text(call(client, ADMIN, sid, "export_subject_data", args))["review_count"] == 0
    assert c.analysis.latest("SHADY") is None  # derived analysis embedding the subject is invalidated
    assert ("r", "ring0") not in c.graph.graph  # graph edges gone
    assert "ring0" not in set(c.index.users)  # text index rebuilt
    with c.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM erasure_requests WHERE reference='DSR-2026-001'").fetchone()[0] == 1
        assert conn.execute("SELECT review_count FROM products WHERE id='SIDE1'").fetchone()[0] == 39
    from app.governance.lifecycle import subject_hash

    suppression = settings.db_path.parent / "erasure_suppression.txt"
    assert subject_hash("ring0") in suppression.read_text().split()
    # the erased subject's raw id is not in the register, only its hash
    with c.db.connect() as conn:
        assert "ring0" not in json.dumps([dict(r) for r in conn.execute("SELECT * FROM erasure_requests")])


def test_subject_rights_are_admin_only(client):
    sid, _ = open_session(client, REVIEWER)
    r = call(client, REVIEWER, sid, "erase_subject_data", {"user_id": "ring0", "reference": "X-1"}).json()["result"]
    assert r["isError"]


def test_governance_resources(client):
    sid, _ = open_session(client, VIEWER)
    pol = json.loads(rpc(client, VIEWER, "resources/read", {"uri": "trace://governance/data-policy"}, session=sid).json()["result"]["contents"][0]["text"])
    assert pol["role_clearance"]["viewer"] == "internal" and pol["third_party_processors"]["gemini"]["approved"] is False
    assert rpc(client, VIEWER, "resources/read", {"uri": "trace://governance/quality"}, session=sid).json()["error"]
    cat = json.loads(rpc(client, VIEWER, "resources/read", {"uri": "trace://governance/catalog"}, session=sid).json()["result"]["contents"][0]["text"])
    assert {a["table"] for a in cat["assets"]} >= {"reviews", "analyses", "llm_egress_ledger"}

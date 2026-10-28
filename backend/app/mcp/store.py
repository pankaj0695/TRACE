"""Persistence for governance records: the tamper-evident audit chain and human reviewer decisions."""

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app.data.database import Database

GENESIS = "0" * 64
DECISIONS = (
    "no_action",
    "monitor",
    "request_seller_audit",
    "escalate_to_abuse_team",
    "dismiss_false_positive",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _digest(prev: str, fields: list) -> str:
    return hashlib.sha256((prev + json.dumps(fields, separators=(",", ":"), sort_keys=True)).encode()).hexdigest()


@dataclass
class AuditEntry:
    session_id: str | None
    principal: str
    role: str
    transport: str
    method: str
    target: str | None
    args: str | None
    outcome: str  # ok | denied | rate_limited | invalid | error | unauthenticated | attempt
    detail: str | None = None
    duration_ms: int | None = None


class AuditStore:
    """Append-only log; every row commits to its predecessor (SHA-256 chain), so edits or deletions are detectable."""

    COLUMNS = "id, ts, session_id, principal, role, transport, method, target, args, outcome, detail, duration_ms, prev_hash, hash"

    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()

    @staticmethod
    def _fields(ts: str, e: AuditEntry) -> list:
        return [ts, e.session_id, e.principal, e.role, e.transport, e.method, e.target, e.args, e.outcome, e.detail,
                e.duration_ms]  # fmt: skip

    def record(self, entry: AuditEntry) -> int:
        with self._lock, self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # serialises writers across threads *and* processes
            row = conn.execute("SELECT hash FROM mcp_audit ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                prev = row["hash"]
            else:  # empty table: continue from the retention checkpoint if old rows were purged
                cp = conn.execute("SELECT last_hash FROM mcp_audit_checkpoint WHERE id = 1").fetchone()
                prev = cp["last_hash"] if cp else GENESIS
            ts = _now()
            cur = conn.execute(
                "INSERT INTO mcp_audit (ts, session_id, principal, role, transport, method, target, args, outcome,"
                " detail, duration_ms, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*self._fields(ts, entry), prev, _digest(prev, self._fields(ts, entry))),
            )
            return int(cur.lastrowid)

    def tail(self, limit: int = 50, principal: str | None = None, outcome: str | None = None) -> list[dict]:
        where, params = [], []
        if principal:
            where.append("principal = ?")
            params.append(principal)
        if outcome:
            where.append("outcome = ?")
            params.append(outcome)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT {self.COLUMNS} FROM mcp_audit {clause} ORDER BY id DESC LIMIT ?", [*params, limit]
            ).fetchall()
        return [{k: r[k] for k in r.keys() if k not in ("prev_hash",)} for r in rows]

    def verify(self) -> dict:
        prev, count, floor = GENESIS, 0, 0
        with self.db.connect() as conn:
            cp = conn.execute("SELECT last_purged_id, last_hash FROM mcp_audit_checkpoint WHERE id = 1").fetchone()
            if cp:  # older rows were purged under the retention policy; the chain resumes from the checkpoint
                prev, floor = cp["last_hash"], cp["last_purged_id"]
            for r in conn.execute(f"SELECT {self.COLUMNS} FROM mcp_audit WHERE id > ? ORDER BY id", (floor,)):
                fields = [r["ts"], r["session_id"], r["principal"], r["role"], r["transport"], r["method"], r["target"],
                          r["args"], r["outcome"], r["detail"], r["duration_ms"]]  # fmt: skip
                if r["prev_hash"] != prev or r["hash"] != _digest(prev, fields):
                    return {"intact": False, "entries_checked": count, "first_broken_id": r["id"]}
                prev, count = r["hash"], count + 1
        return {"intact": True, "entries_checked": count, "head": prev, "checkpoint_id": floor or None}


class DecisionStore:
    """Human reviewer decisions. TRACE only records them; it never executes enforcement."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, *, product_id, decision, rationale, principal, role, session_id, analysis) -> dict:
        created = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO reviewer_decisions (product_id, decision, rationale, principal, role, session_id,"
                " analysis_created_at, risk_score, tier, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (product_id, decision, rationale, principal, role, session_id, analysis.created_at.isoformat(),
                 analysis.assessment.risk_score, analysis.assessment.tier.value, created),
            )  # fmt: skip
            decision_id = cur.lastrowid
        return {"id": decision_id, "product_id": product_id, "decision": decision, "recorded_by": principal,
                "created_at": created}  # fmt: skip

    def for_product(self, product_id: str, limit: int = 20) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, product_id, decision, rationale, principal, role, risk_score, tier, analysis_created_at,"
                " created_at FROM reviewer_decisions WHERE product_id = ? ORDER BY id DESC LIMIT ?",
                (product_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_by_product(self, product_ids: list[str]) -> dict[str, dict]:
        if not product_ids:
            return {}
        marks = ",".join("?" * len(product_ids))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"SELECT product_id, decision, principal, created_at FROM reviewer_decisions WHERE id IN"
                f" (SELECT MAX(id) FROM reviewer_decisions WHERE product_id IN ({marks}) GROUP BY product_id)",
                product_ids,
            ).fetchall()
        return {r["product_id"]: dict(r) for r in rows}

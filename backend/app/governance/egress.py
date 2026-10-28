"""Controls on data leaving the system for a third-party LLM: approval, minimisation, ledger, output filtering."""

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from app.data.database import Database
from app.governance.policy import PROCESSORS, approved_processors
from app.llm.client import LLMClient, LLMUnavailable
from app.mcp.governance import redact_text, scrub

log = logging.getLogger(__name__)
PURPOSE = "reviewer_report_drafting"
# Amazon reviewer ids: 'A' + ~27 upper-case alphanumerics. ASINs are 10 chars so they are not matched.
_REVIEWER_ID = re.compile(r"\bA[A-Z0-9]{20,27}\b")


class Pseudonymizer:
    """Stable keyed pseudonyms. The key lives in the database, so pseudonyms survive restarts but not a rebuild."""

    def __init__(self, db: Database):
        self._key = self._load_key(db)

    @staticmethod
    def _load_key(db: Database) -> bytes:
        with db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO governance_meta (key, value) VALUES ('pseudonym_key', ?)", (secrets.token_hex(32),))
            return conn.execute("SELECT value FROM governance_meta WHERE key='pseudonym_key'").fetchone()["value"].encode()

    def token(self, identifier: str) -> str:
        return "reviewer-" + hmac.new(self._key, identifier.encode(), hashlib.sha256).hexdigest()[:10]

    def apply(self, text: str) -> tuple[str, int]:
        count = 0

        def swap(m: re.Match) -> str:
            nonlocal count
            count += 1
            return self.token(m.group(0))

        return _REVIEWER_ID.sub(swap, text), count


class EgressLedger:
    """Evidence of what was sent to whom and why - hashes and sizes only, never the payload."""

    def __init__(self, db: Database):
        self.db = db

    def record(self, **f: Any) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO llm_egress_ledger (ts, processor, model, purpose, data_classes, bytes_sent, redactions,"
                " payload_sha256, outcome, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="milliseconds"), f["processor"], f.get("model"),
                 f["purpose"], ",".join(f["data_classes"]), f["bytes_sent"], f["redactions"], f["payload_sha256"],
                 f["outcome"], f.get("detail")),
            )  # fmt: skip

    def tail(self, limit: int = 50) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM llm_egress_ledger ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT outcome, COUNT(*) n, COALESCE(SUM(bytes_sent),0) b FROM llm_egress_ledger GROUP BY outcome").fetchall()
        return {r["outcome"]: {"calls": r["n"], "bytes": r["b"]} for r in rows}


class GovernedLLM:
    """Wraps an external LLM client. Order of controls: approval -> minimise -> ledger (fail closed) -> call -> filter."""

    processor = "gemini"

    def __init__(self, inner: LLMClient, settings, pseudonyms: Pseudonymizer, ledger: EgressLedger):
        self.inner, self.settings, self.pseudonyms, self.ledger = inner, settings, pseudonyms, ledger
        if self.processor not in approved_processors(settings):
            log.warning(
                "LLM key is configured but '%s' is not in TRACE_APPROVED_PROCESSORS: reports will be rule-based. "
                "Approve it after your data-protection review (see docs/DATA_GOVERNANCE.md).",
                self.processor,
            )

    @property
    def name(self) -> str:
        return self.inner.name

    def _blocked_reason(self) -> str | None:
        if self.settings.llm_egress_mode == "off":
            return "LLM egress mode is 'off'"
        if self.processor not in approved_processors(self.settings):
            return f"processor '{self.processor}' is not approved (TRACE_APPROVED_PROCESSORS)"
        return None

    def minimise(self, text: str) -> tuple[str, int]:
        text, ids = self.pseudonyms.apply(text)
        cleaned = redact_text(text)
        redactions = ids + sum(1 for a, b in zip(text, cleaned, strict=False) if a != b)  # coarse but monotonic
        limit = self.settings.llm_max_prompt_chars
        if len(cleaned) > limit:
            cleaned, redactions = cleaned[:limit] + "\n[truncated by data-minimisation policy]", redactions + 1
        return cleaned, redactions

    async def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        base = {"processor": self.processor, "model": self.inner.name, "purpose": PURPOSE, "data_classes": ["internal"]}
        reason = self._blocked_reason()
        if reason:
            self._log(base | {"bytes_sent": 0, "redactions": 0, "payload_sha256": "-", "outcome": "blocked", "detail": reason})
            raise LLMUnavailable(f"blocked by data governance: {reason}")
        system, n1 = self.minimise(system)
        prompt, n2 = self.minimise(prompt)
        body = (system + "\n" + prompt).encode()
        entry = base | {"bytes_sent": len(body), "redactions": n1 + n2, "payload_sha256": hashlib.sha256(body).hexdigest()}
        try:
            self.ledger.record(**entry, outcome="sent")
        except Exception as exc:  # no record, no egress
            raise LLMUnavailable("egress ledger unavailable; call withheld") from exc
        result = await self.inner.generate_json(system, prompt, schema)
        return scrub(result, max_string=2000)

    def _log(self, entry: dict) -> None:
        try:
            self.ledger.record(**entry)
        except Exception:  # pragma: no cover
            log.error("egress ledger write failed")


def processor_status(settings) -> dict:
    ok = approved_processors(settings)
    return {k: {"approved": k in ok, "purpose": v["purpose"], "data_sent": v["data_sent"]} for k, v in PROCESSORS.items()}

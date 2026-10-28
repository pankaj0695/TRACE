"""Aggregates the data-governance services so the container and entry points share one wiring."""

from datetime import datetime, timezone

from app.data.database import Database
from app.governance.egress import EgressLedger, Pseudonymizer
from app.governance.lifecycle import RetentionService, SubjectRights
from app.governance.policy import POLICY_VERSION, approved_processors, retention_days
from app.governance.quality import QualityService, dataset_fingerprint, product_quality


class GovernanceServices:
    def __init__(self, settings, db: Database):
        self.settings, self.db = settings, db
        self.pseudonyms = Pseudonymizer(db)
        self.ledger = EgressLedger(db)
        self.quality = QualityService(db)
        self.retention = RetentionService(db, settings)
        self.rights = SubjectRights(db, settings.db_path.parent / "erasure_suppression.txt")
        self.dataset = dataset_fingerprint(db)

    def refresh_dataset(self) -> None:
        self.dataset = dataset_fingerprint(self.db)

    def lineage(self, state: dict) -> dict:
        """Provenance stamped on every saved analysis: what data, which agents, which processors, which policy."""
        ctx, signals, report = state["context"], state["signals"], state["report"]
        used_llm = report.generated_by != "rules"
        return {
            "dataset": self.dataset,
            "inputs": {"reviews": len(ctx.reviews), "reviewers": len(ctx.reviewers), "baselines": sorted(ctx.baselines)},
            "quality": product_quality(ctx),
            "agents": {k: {"status": s.status, "duration_ms": s.duration_ms} for k, s in signals.items()},
            "report_generated_by": report.generated_by,
            "third_party_processors": ["gemini"] if used_llm else [],
            "approved_processors": sorted(approved_processors(self.settings)),
            "governance": {
                "policy_version": POLICY_VERSION,
                "classification": "confidential",
                "purpose": "abuse_detection",
                "retention_days": retention_days(self.settings)["analyses"],
            },
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

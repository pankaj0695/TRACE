from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    INSUFFICIENT = "insufficient_data"

    @classmethod
    def from_score(cls, score: float) -> "RiskTier":
        if score >= 75:
            return cls.CRITICAL
        if score >= 50:
            return cls.HIGH
        if score >= 25:
            return cls.MEDIUM
        return cls.LOW


class Product(BaseModel):
    id: str
    title: str
    store: str | None = None
    avg_rating: float | None = None
    rating_count: int | None = None
    price: float | None = None
    image_url: str | None = None
    features: list[str] = []
    review_count: int = 0
    spike_ratio: float = 0.0


class Review(BaseModel):
    id: int
    product_id: str
    user_id: str
    rating: float
    title: str = ""
    text: str = ""
    ts: int
    verified: bool
    helpful: int = 0
    has_images: bool = False


class ReviewerProfile(BaseModel):
    user_id: str
    review_count: int
    first_ts: int
    distinct_stores: int
    store_share: float = Field(description="Share of this reviewer's reviews on the product's store")
    verified_rate: float


class ProductContext(BaseModel):
    """Everything the detection agents need, assembled once by the ingestion agent."""

    product: Product
    reviews: list[Review]
    reviewers: dict[str, ReviewerProfile]
    baselines: dict[str, float]


class Finding(BaseModel):
    code: str
    title: str
    detail: str
    severity: Severity
    evidence: dict[str, Any] = {}


class AgentSignal(BaseModel):
    agent: str
    status: Literal["ok", "failed", "skipped"] = "ok"
    risk: float = Field(0.0, ge=0, le=1)
    confidence: float = Field(0.0, ge=0, le=1)
    summary: str = ""
    metrics: dict[str, Any] = {}
    findings: list[Finding] = []
    artifacts: dict[str, Any] = Field(default={}, description="Chart/graph payloads for the UI")
    duration_ms: int = 0
    error: str | None = None


class Assessment(BaseModel):
    risk_score: float
    trust_score: float
    tier: RiskTier
    weights: dict[str, float]
    conflict: bool
    needs_manual_review: bool


class PolicyFinding(BaseModel):
    title: str
    detail: str
    severity: Severity
    policy: str
    agent: str


class TrustReport(BaseModel):
    headline: str
    summary: str
    findings: list[PolicyFinding]
    recommendations: list[str]
    reviewer_note: str
    generated_by: str


class Analysis(BaseModel):
    product: Product
    signals: dict[str, AgentSignal]
    assessment: Assessment
    report: TrustReport
    created_at: datetime


class AnalysisSummary(BaseModel):
    product_id: str
    risk_score: float
    tier: RiskTier
    created_at: datetime

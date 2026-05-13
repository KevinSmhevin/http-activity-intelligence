from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LabelSource(StrEnum):
    LLM = "llm"
    FALLBACK = "fallback"
    CACHE = "cache"


class SessionConfig(BaseModel):
    gap_threshold_seconds: int = 300
    idle_cutoff_seconds: int = 1200
    dedup_window_seconds: float = 2.0
    top_n_hosts: int = 5
    top_n_paths_per_host: int = 3


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    method: str
    host: str
    path: str | None
    status_code: int | None
    bytes_out: int
    bytes_in: int | None
    source_app: str
    tab_id: str | None
    referrer: str | None
    client_ip: str

    apex_domain: str
    engagement_key: str
    is_foreground: bool
    is_duplicate: bool


class Label(BaseModel):
    text: str
    confidence: Confidence
    source: LabelSource | None = None
    evidence: list[str] = Field(default_factory=list)


class IdleInterval(BaseModel):
    start: datetime
    end: datetime
    duration_seconds: float
    background_apps: set[str] = Field(default_factory=set)


class Session(BaseModel):
    id: str
    engagement_key: str
    source_app: str
    apex_domain: str | None
    context: str | None
    start: datetime
    end: datetime
    duration_seconds: float
    event_count: int
    fragmentation_score: float
    distinct_tabs: int
    distinct_hosts: int
    dominant_hosts: list[tuple[str, int]]
    top_paths: list[tuple[str, int]]
    content_hash: str

    label: Label | None = None


class FocusRanking(BaseModel):
    most_sustained: Session
    most_fragmented: Session
    method: str


class TimeBucket(BaseModel):
    category: str
    total_seconds: float
    session_count: int
    session_ids: list[str]


class Timeline(BaseModel):
    start: datetime
    end: datetime
    sessions: list[Session]
    idle_intervals: list[IdleInterval]

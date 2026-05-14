from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from .idle import detect_idle
from .labeler import label_session
from .models import (
    Event,
    FocusRanking,
    Label,
    Session,
    SessionConfig,
    TimeBucket,
)
from .repository import Repository
from .sessionizer import sessionize


_FRAGMENTATION_METHOD = "distinct (apex_domain, tab_id) pairs per minute of session duration"
_LABEL_WORKERS = 8


class ActivityIntelligence:
    def __init__(
        self,
        repository: Repository,
        config: SessionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.config = config or SessionConfig()
        self._label_cache: dict[str, Label] = {}

    def list_sessions(self, *, with_labels: bool = True) -> list[Session]:
        sessions = sessionize(self.repository.events, self.config)
        if not with_labels:
            return sessions

        def _label(session: Session) -> None:
            session.label = label_session(
                session, self._events_for(session), self._label_cache
            )

        with ThreadPoolExecutor(max_workers=_LABEL_WORKERS) as pool:
            list(pool.map(_label, sessions))
        return sessions

    def focus_ranking(self) -> FocusRanking:
        sessions = self.list_sessions()
        if len(sessions) < 2:
            raise ValueError(
                f"focus_ranking requires at least 2 sessions; got {len(sessions)}"
            )
        sorted_sessions = sorted(sessions, key=lambda s: s.fragmentation_score)
        return FocusRanking(
            most_sustained=sorted_sessions[0],
            most_fragmented=sorted_sessions[-1],
            method=_FRAGMENTATION_METHOD,
        )

    def time_breakdown(
        self,
        group_by: Literal["label", "apex_domain", "source_app"] = "label",
    ) -> list[TimeBucket]:
        sessions = self.list_sessions()
        key_fn = _resolve_grouping_key(group_by)
        groups = _group_sessions_by_key(sessions, key_fn)
        buckets = [_bucket_from_group(cat, sess) for cat, sess in groups.items()]

        idle_intervals = detect_idle(self.repository.events, self.config)
        if idle_intervals:
            buckets.append(_idle_bucket(idle_intervals))

        buckets.sort(key=lambda b: -b.total_seconds)
        return buckets

    def _events_for(self, session: Session) -> list[Event]:
        return [
            e
            for e in self.repository.events
            if e.source_app == session.source_app
            and session.start <= e.timestamp <= session.end
            and e.is_foreground
            and not e.is_duplicate
        ]


def _resolve_grouping_key(group_by: str) -> Callable[[Session], str]:
    if group_by == "label":
        return _key_by_label
    if group_by == "apex_domain":
        return _key_by_apex_domain
    return _key_by_source_app


def _key_by_label(session: Session) -> str:
    return session.label.text if session.label else session.source_app


def _key_by_apex_domain(session: Session) -> str:
    if session.source_app == "chrome" and session.context:
        return session.context
    return session.source_app


def _key_by_source_app(session: Session) -> str:
    return session.source_app


def _group_sessions_by_key(
    sessions: list[Session], key_fn: Callable[[Session], str]
) -> dict[str, list[Session]]:
    groups: dict[str, list[Session]] = defaultdict(list)
    for session in sessions:
        groups[key_fn(session)].append(session)
    return groups


def _bucket_from_group(category: str, sessions: list[Session]) -> TimeBucket:
    return TimeBucket(
        category=category,
        total_seconds=sum(s.duration_seconds for s in sessions),
        session_count=len(sessions),
        session_ids=[s.id for s in sessions],
    )


def _idle_bucket(intervals) -> TimeBucket:
    return TimeBucket(
        category="idle / away",
        total_seconds=sum(iv.duration_seconds for iv in intervals),
        session_count=len(intervals),
        session_ids=[],
    )

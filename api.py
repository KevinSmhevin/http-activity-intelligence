from collections import defaultdict
from typing import Literal

from idle import detect_idle
from labeler import label
from models import (
    Event,
    FocusRanking,
    LabelSource,
    Session,
    SessionConfig,
    TimeBucket,
)
from repository import Repository
from sessionizer import sessionize


_FRAGMENTATION_METHOD = "distinct (apex_domain, tab_id) pairs per minute of session duration"


class ActivityIntelligence:
    def __init__(
        self,
        repository: Repository,
        config: SessionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.config = config or SessionConfig()

    def list_sessions(self) -> list[Session]:
        sessions = sessionize(self.repository.events, self.config)
        for session in sessions:
            session_events = self._events_for(session)
            result = label(session, session_events)
            session.label = result.model_copy(update={"source": LabelSource.FALLBACK})
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

        def key_for(session: Session) -> str:
            if group_by == "label":
                return session.label.text if session.label else session.source_app
            if group_by == "apex_domain":
                if session.source_app == "chrome" and session.context:
                    return session.context
                return session.source_app
            return session.source_app

        groups: dict[str, list[Session]] = defaultdict(list)
        for session in sessions:
            groups[key_for(session)].append(session)

        buckets = [
            TimeBucket(
                category=category,
                total_seconds=sum(s.duration_seconds for s in sess),
                session_count=len(sess),
                session_ids=[s.id for s in sess],
            )
            for category, sess in groups.items()
        ]

        intervals = detect_idle(self.repository.events, self.config)
        if intervals:
            buckets.append(
                TimeBucket(
                    category="idle / away",
                    total_seconds=sum(iv.duration_seconds for iv in intervals),
                    session_count=len(intervals),
                    session_ids=[],
                )
            )

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

from itertools import groupby
from operator import attrgetter

from models import Event, Session, SessionConfig


def sessionize(events: list[Event], config: SessionConfig) -> list[Session]:
    foreground = [e for e in events if e.is_foreground and not e.is_duplicate]
    foreground.sort(key=attrgetter("source_app", "timestamp"))

    sessions: list[Session] = []
    gap = config.gap_threshold_seconds

    for source_app, group in groupby(foreground, key=attrgetter("source_app")):
        chunk: list[Event] = []
        for e in group:
            if chunk and (e.timestamp - chunk[-1].timestamp).total_seconds() > gap:
                sessions.append(_build_session(chunk, source_app))
                chunk = []
            chunk.append(e)
        if chunk:
            sessions.append(_build_session(chunk, source_app))

    sessions.sort(key=lambda s: s.start)
    return sessions


def _build_session(events: list[Event], source_app: str) -> Session:
    start = events[0].timestamp
    end = events[-1].timestamp
    return Session(
        id=f"{source_app}:{start.isoformat()}",
        engagement_key=source_app,
        source_app=source_app,
        apex_domain=None,
        start=start,
        end=end,
        duration_seconds=(end - start).total_seconds(),
        event_count=len(events),
        fragmentation=0.0,
        distinct_tabs=0,
        distinct_hosts=0,
        top_hosts=[],
        top_paths=[],
        content_hash="",
    )

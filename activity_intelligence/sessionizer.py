from collections import Counter
from itertools import groupby
from operator import attrgetter

from .models import Event, Session, SessionConfig


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
    duration_seconds = (end - start).total_seconds()
    duration_minutes = max(duration_seconds / 60.0, 1.0)

    distinct_pairs = {(e.apex_domain, e.tab_id) for e in events}
    fragmentation_score = len(distinct_pairs) / duration_minutes

    distinct_tabs = {e.tab_id for e in events if e.tab_id is not None}
    distinct_hosts = {e.host for e in events}
    dominant_hosts = Counter(e.apex_domain for e in events).most_common(3)

    context = dominant_hosts[0][0] if source_app == "chrome" and dominant_hosts else None

    return Session(
        id=f"{source_app}:{start.isoformat()}",
        engagement_key=source_app,
        source_app=source_app,
        apex_domain=None,
        context=context,
        start=start,
        end=end,
        duration_seconds=duration_seconds,
        event_count=len(events),
        fragmentation_score=fragmentation_score,
        distinct_tabs=len(distinct_tabs),
        distinct_hosts=len(distinct_hosts),
        dominant_hosts=dominant_hosts,
        top_paths=[],
        content_hash="",
    )

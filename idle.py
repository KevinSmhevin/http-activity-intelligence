from operator import attrgetter

from models import Event, IdleInterval, SessionConfig


def detect_idle(events: list[Event], config: SessionConfig) -> list[IdleInterval]:
    foreground = sorted(
        (e for e in events if e.is_foreground and not e.is_duplicate),
        key=attrgetter("timestamp"),
    )
    if len(foreground) < 2:
        return []

    background = [e for e in events if not e.is_foreground and not e.is_duplicate]
    cutoff = config.idle_cutoff_seconds
    intervals: list[IdleInterval] = []

    for prev, curr in zip(foreground, foreground[1:]):
        gap = (curr.timestamp - prev.timestamp).total_seconds()
        if gap >= cutoff:
            apps = {
                e.source_app
                for e in background
                if prev.timestamp <= e.timestamp <= curr.timestamp
            }
            intervals.append(
                IdleInterval(
                    start=prev.timestamp,
                    end=curr.timestamp,
                    duration_seconds=gap,
                    background_apps=apps,
                )
            )

    return intervals

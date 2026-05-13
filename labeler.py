from collections import Counter

from models import Confidence, Event, Label, Session


def label(session: Session, events: list[Event]) -> Label:
    top_host = Counter(e.host for e in events).most_common(1)[0][0]
    return Label(
        text=f"Activity on {top_host}",
        confidence=Confidence.LOW,
        evidence=[],
    )

from models import Event, LabelSource, Session, SessionConfig
from repository import Repository
from labeler import label
from sessionizer import sessionize


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
            session.label = result.label
            session.label_confidence = result.confidence
            session.label_evidence = result.evidence
            session.label_source = LabelSource.FALLBACK
        return sessions

    def _events_for(self, session: Session) -> list[Event]:
        return [
            e
            for e in self.repository.events
            if e.source_app == session.source_app
            and session.start <= e.timestamp <= session.end
            and e.is_foreground
            and not e.is_duplicate
        ]

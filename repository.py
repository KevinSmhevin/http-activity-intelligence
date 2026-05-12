from pathlib import Path

from models import Event


class Repository:
    def __init__(self, events: list[Event]) -> None:
        self.events = events

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "Repository":
        return cls(events=[])

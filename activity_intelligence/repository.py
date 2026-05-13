from .models import Event


class Repository:
    def __init__(self, events: list[Event]) -> None:
        self.events = events

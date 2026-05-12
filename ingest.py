import json
from datetime import datetime, timezone
from pathlib import Path

from models import Event


def load_events(path: str | Path) -> list[Event]:
    events: list[Event] = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            ts = datetime.fromisoformat(raw["timestamp"]).astimezone(timezone.utc)
            host = raw["host"]
            source_app = raw["source_app"]
            engagement_key = host if source_app == "chrome" else source_app
            events.append(
                Event(
                    timestamp=ts,
                    method=raw["method"],
                    host=host,
                    path=raw.get("path"),
                    status_code=raw.get("status_code"),
                    bytes_out=raw["bytes_out"],
                    bytes_in=raw.get("bytes_in"),
                    source_app=source_app,
                    tab_id=raw.get("tab_id"),
                    referrer=raw.get("referrer"),
                    client_ip=raw["client_ip"],
                    apex_domain=host,
                    engagement_key=engagement_key,
                    is_foreground=True,
                    is_duplicate=False,
                )
            )
    return events

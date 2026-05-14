import json
from datetime import datetime, timezone
from pathlib import Path

from .classify import classify_foreground
from .models import Event, SessionConfig


def _apex_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) < 2:
        return host
    return ".".join(parts[-2:])


def read_raw_events(path: str | Path) -> list[dict]:
    raws: list[dict] = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raws.append(json.loads(line))
    return raws


def normalize_timestamps(raws: list[dict]) -> list[dict]:
    for raw in raws:
        raw["_ts"] = datetime.fromisoformat(raw["timestamp"]).astimezone(timezone.utc)
    return sorted(raws, key=lambda r: r["_ts"])


def mark_duplicates(raws: list[dict], window_seconds: float) -> None:
    last_seen: dict[tuple, datetime] = {}
    for raw in raws:
        key = (
            raw["host"],
            raw.get("path"),
            raw["method"],
            raw["bytes_out"],
            raw.get("bytes_in"),
        )
        last_ts = last_seen.get(key)
        raw["_duplicate"] = (
            last_ts is not None
            and (raw["_ts"] - last_ts).total_seconds() <= window_seconds
        )
        last_seen[key] = raw["_ts"]


def build_events(raws: list[dict]) -> list[Event]:
    return [_raw_to_event(raw) for raw in raws]


def _raw_to_event(raw: dict) -> Event:
    host = raw["host"]
    source_app = raw["source_app"]
    candidate = Event(
        timestamp=raw["_ts"],
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
        apex_domain=_apex_domain(host),
        engagement_key=host if source_app == "chrome" else source_app,
        is_foreground=True,
        is_duplicate=raw["_duplicate"],
    )
    return candidate.model_copy(update={"is_foreground": classify_foreground(candidate)})


def load_events(path: str | Path, config: SessionConfig | None = None) -> list[Event]:
    cfg = config or SessionConfig()
    raws = read_raw_events(path)
    raws = normalize_timestamps(raws)
    mark_duplicates(raws, cfg.dedup_window_seconds)
    return build_events(raws)

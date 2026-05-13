import argparse

from api import ActivityIntelligence
from idle import detect_idle
from ingest import load_events
from repository import Repository


def cmd_sessions(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    for session in ai.list_sessions():
        print(session.model_dump_json())


def cmd_stats(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    sessions = ai.list_sessions()
    intervals = detect_idle(events, ai.config)

    foreground = sum(e.is_foreground for e in events)
    background = sum(not e.is_foreground for e in events)
    duplicates = sum(e.is_duplicate for e in events)

    print(f"total events:    {len(events):>6,}")
    print(f"foreground:      {foreground:>6,}")
    print(f"background:      {background:>6,}")
    print(f"duplicates:      {duplicates:>6,}")
    print(f"sessions:        {len(sessions):>6,}")
    print(f"idle intervals:  {len(intervals):>6,}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="activity-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sessions = sub.add_parser("sessions", help="List activity sessions as JSON lines")
    p_sessions.add_argument("path", help="Path to http_events.jsonl")
    p_sessions.set_defaults(func=cmd_sessions)

    p_stats = sub.add_parser("stats", help="Print pipeline counts")
    p_stats.add_argument("path", help="Path to http_events.jsonl")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

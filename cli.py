import argparse

from api import ActivityIntelligence
from ingest import load_events
from repository import Repository


def cmd_sessions(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    for session in ai.list_sessions():
        print(session.model_dump_json())


def main() -> None:
    parser = argparse.ArgumentParser(prog="activity-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sessions = sub.add_parser("sessions", help="List activity sessions as JSON lines")
    p_sessions.add_argument("path", help="Path to http_events.jsonl")
    p_sessions.set_defaults(func=cmd_sessions)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

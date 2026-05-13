import argparse

from .api import ActivityIntelligence
from .idle import detect_idle
from .ingest import load_events
from .repository import Repository
from .sessionizer import sessionize


def cmd_sessions(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    for session in ai.list_sessions(with_labels=not args.no_labels):
        print(session.model_dump_json())


def cmd_stats(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    sessions = sessionize(events, ai.config)
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


def cmd_focus_ranking(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    ranking = ai.focus_ranking()

    def describe(session) -> str:
        label_text = session.label.text if session.label else "(none)"
        return (
            f"  frag_score: {session.fragmentation_score:.3f}\n"
            f"  id:         {session.id}\n"
            f"  label:      {label_text}\n"
            f"  duration:   {session.duration_seconds / 60:.1f} min\n"
            f"  events:     {session.event_count}\n"
            f"  dominant:   {session.dominant_hosts}"
        )

    print(f"method: {ranking.method}")
    print()
    print("most_sustained:")
    print(describe(ranking.most_sustained))
    print()
    print("most_fragmented:")
    print(describe(ranking.most_fragmented))


def cmd_time_breakdown(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    buckets = ai.time_breakdown(group_by=args.group_by)
    for b in buckets:
        print(f"{b.total_seconds / 60:8.1f}m  ({b.session_count:>3}x)  {b.category}")


def cmd_run(args: argparse.Namespace) -> None:
    events = load_events(args.path)
    ai = ActivityIntelligence(Repository(events=events))
    sessions = ai.list_sessions()
    intervals = detect_idle(events, ai.config)

    rows: list[tuple] = [("session", s.start, s) for s in sessions]
    rows += [("idle", iv.start, iv) for iv in intervals]
    rows.sort(key=lambda r: r[1])

    for kind, _, item in rows:
        start = item.start.strftime("%H:%M")
        end = item.end.strftime("%H:%M")
        dur = item.duration_seconds / 60
        if kind == "session":
            label_text = item.label.text if item.label else "(none)"
            conf = item.label.confidence.value if item.label else "?"
            ctx = item.context or item.source_app
            print(
                f"{start}-{end}  {dur:>5.1f}m   [{conf}]  {label_text}   "
                f"({ctx}, frag={item.fragmentation_score:.2f})"
            )
        else:
            print(f"{start}-{end}  {dur:>5.1f}m   ──── idle ────")


def main() -> None:
    parser = argparse.ArgumentParser(prog="activity-intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sessions = sub.add_parser("sessions", help="List activity sessions as JSON lines")
    p_sessions.add_argument("path", help="Path to http_events.jsonl")
    p_sessions.add_argument(
        "--no-labels",
        action="store_true",
        help="Skip LLM labeling (fast, no API key needed; `label` will be null)",
    )
    p_sessions.set_defaults(func=cmd_sessions)

    p_stats = sub.add_parser("stats", help="Print pipeline counts")
    p_stats.add_argument("path", help="Path to http_events.jsonl")
    p_stats.set_defaults(func=cmd_stats)

    p_focus = sub.add_parser(
        "focus-ranking",
        help="Most sustained-focus and most fragmented session",
    )
    p_focus.add_argument("path", help="Path to http_events.jsonl")
    p_focus.set_defaults(func=cmd_focus_ranking)

    p_time = sub.add_parser(
        "time-breakdown",
        help="Cumulative time grouped by label / apex_domain / source_app, plus idle",
    )
    p_time.add_argument("path", help="Path to http_events.jsonl")
    p_time.add_argument(
        "--group-by",
        choices=["label", "apex_domain", "source_app"],
        default="label",
        help="Grouping dimension (default: label)",
    )
    p_time.set_defaults(func=cmd_time_breakdown)

    p_run = sub.add_parser(
        "run",
        help="Run the full pipeline and print the interleaved timeline",
    )
    p_run.add_argument("path", help="Path to http_events.jsonl")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

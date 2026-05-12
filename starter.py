"""
Minimal starter. Run this to confirm you can load the dataset.
It does the absolute minimum: opens the file, parses each line as JSON,
prints a few stats. Replace it with whatever you want — it has no opinions
about your data model, your storage, or your sessionization.
"""

import json
from collections import Counter
from pathlib import Path

DATA_FILE = Path(__file__).parent / "http_events.jsonl"


def load_events():
    with DATA_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main():
    events = list(load_events())
    print(f"Loaded {len(events):,} events")
    print(f"First timestamp: {events[0]['timestamp']}")
    print(f"Last timestamp:  {events[-1]['timestamp']}")

    print("\nTop 5 hosts by raw count:")
    for host, n in Counter(e["host"] for e in events).most_common(5):
        print(f"  {n:>5}  {host}")

    print("\nSource apps:")
    for app, n in Counter(e["source_app"] for e in events).most_common():
        print(f"  {n:>5}  {app}")


if __name__ == "__main__":
    main()

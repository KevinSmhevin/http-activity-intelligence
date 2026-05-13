# HTTP Activity Intelligence

Turns a stream of HTTP events captured from a laptop into a model of how the
user actually spent their time: distinct activity sessions, focus vs.
fragmentation rankings, where the time went, and a short LLM-generated label
for each session — grounded in the session's actual contents.

Built as a take-home assessment against `data/http_events.jsonl` (5,101 events,
~17 hours of one user's traffic). See [`INSTRUCTIONS.md`](INSTRUCTIONS.md) for
the original prompt and [`docs/design.md`](docs/design.md) for the design
write-up.

## Layout

```
activity_intelligence/     # Python package
  ingest.py                # JSONL → normalized Event records (TZ, dedupe, foreground tag)
  classify.py              # foreground/background heuristic
  sessionizer.py           # foreground events → Session records (gap-split per source_app)
  idle.py                  # global foreground gaps ≥ 20 min → IdleInterval
  labeler.py               # grounded LLM labeler with retry, fallback, and content-hash cache
  api.py                   # ActivityIntelligence: list_sessions / focus_ranking / time_breakdown
  repository.py            # in-memory event store
  models.py                # Pydantic models + SessionConfig
  cli.py                   # thin argparse CLI
data/
  http_events.jsonl        # input dataset
docs/
  design.md                # design doc (data model, sessionization, labeler, scaling)
  data_exploration.md      # exploration notes that fed the design
tests/
  test_classification.py   # foreground/background heuristic
INSTRUCTIONS.md            # original assessment prompt
CLAUDE.md                  # repo conventions / invariants for Claude Code
```

## Setup

Python 3.12+. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

Set an API key for the labeler (Anthropic by default):

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

`.env` is loaded automatically by the labeler.

## Running

The CLI is a module entry point on the package:

```bash
# Pipeline counts (foreground/background/dupes/sessions/idle)
uv run python -m activity_intelligence stats data/http_events.jsonl

# All sessions as JSON lines (one Session per line, includes label)
uv run python -m activity_intelligence sessions data/http_events.jsonl

# Most-sustained-focus and most-fragmented session
uv run python -m activity_intelligence focus-ranking data/http_events.jsonl

# Where the time went, grouped by label / apex_domain / source_app
uv run python -m activity_intelligence time-breakdown data/http_events.jsonl
uv run python -m activity_intelligence time-breakdown data/http_events.jsonl --group-by apex_domain

# Interleaved timeline (sessions + idle windows in chronological order)
uv run python -m activity_intelligence run data/http_events.jsonl
```

Programmatic use:

```python
from activity_intelligence import ActivityIntelligence, Repository, load_events

events = load_events("data/http_events.jsonl")
ai = ActivityIntelligence(Repository(events=events))

sessions = ai.list_sessions()
ranking = ai.focus_ranking()
buckets = ai.time_breakdown(group_by="label")
```

## Tests

```bash
uv run pytest
```

## Design

See [`docs/design.md`](docs/design.md) for the full write-up: data model,
sessionization choice, grounded LLM labeler (compressed input → tool-use JSON →
literal-evidence check → strict retry → deterministic fallback), and what
would change to scale beyond one user / one day.

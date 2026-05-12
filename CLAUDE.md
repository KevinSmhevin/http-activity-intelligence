# HTTP Activity Intelligence

Take-home assessment ~ 3 hour time budget. Build a system that turns ~5,100 HTTP events captured from one user's laptop over ~24 hours into:
1. An ingestion + modeling layer
2. An API answering three queries (distinct sessions; most-focused / most-fragmented session; what the user spent the most time on)
3. An LLM-powered labeler that produces short, grounded labels for each session
4. A design doc (already written — see `http_activity_intelligence_design_doc.md`)

## Repo layout

- `README.md` — assessment prompt and data schema (do not edit)
- `http_activity_intelligence_design_doc.md` — the source of truth for design decisions
- `http_events.jsonl` — 5,101 events, ~1.4 MB. Schema in `README.md`
- `starter.py` — minimal load-and-print starter; safe to replace
- `requirements.txt` — empty by default; pick libs as needed

## Architecture

- **In-memory `Repository`** holding events as immutable Pydantic `Event` records. No durable storage.
- **Pure functions** `sessionize(events, config) -> list[Session]` and `detect_idle(events, config) -> list[IdleInterval]`. Sessions, metrics, focus rankings are all derived per request.
- **Engagement key** = apex domain for browser events, `source_app` otherwise. NOT `tab_id` (three Google Docs tabs = one engagement).
- **Session boundary** = foreground gap > 5 min within an engagement.
- **Idle interval** = global foreground gap ≥ 20 min (first-class, named).
- **Fragmentation metric** = distinct `(apex_domain, tab_id)` pairs per minute of session duration. Within-session only.
- **Time-on-X** groups sessions by LLM label, with apex domain as fallback.
- **Invocation surface** = Python class + thin CLI. No HTTP service (cut for time).

## LLM labeler invariants

- Model sees a **compressed summary** (source_app, duration, top hosts/paths, fragmentation), not raw events.
- Structured JSON output via tool-use schema: `{label, confidence, evidence[]}`. `temperature=0`.
- **Every `evidence` entry must literally appear** in the compressed input (case-insensitive, subdomain-flexible). Hallucinations are rejected and retried once with a stricter prompt.
- **Deterministic fallback** `"Activity on {dominant_apex_domain}"` with `confidence: low` if both attempts fail. Every session leaves with a non-null label and known `label_source`.
- **Cache key** = SHA-256 of compressed input (not session ID), so reruns at different sessionization params reuse labels.

## Data quirks to remember

- Timestamps mix `-07:00` and `Z` (UTC) — normalize to UTC on ingest.
- A few duplicate events from proxy retries — dedupe on `(host, path, method, bytes_out, bytes_in)` within a 2-second window.
- A few nulls in `path`, `status_code`, `bytes_in`.
- Background polling (Dropbox longpoll, Slack websockets) dominates raw counts — classify foreground/background before sessionizing.
- `client_ip` changes during the day (user moved networks) — don't anchor identity on it.
- At least one extended idle period (~user away from laptop).
- Event mix: dropbox 2043, slack 1653, chrome 1377, terminal 28.

## Conventions

- Python 3.11+. Pydantic for `Event`/`Session`/`IdleInterval` models.
- Pure functions over events + config; no global mutable state outside the label cache.
- Sessionization config (`gap_threshold`, `idle_cutoff`, etc.) lives in a `SessionConfig` dataclass — tunable without touching pipeline code.
- Determinism matters: identical inputs must produce identical sessions and identical content hashes so the label cache survives recomputation.

## Running

```bash
python starter.py   # sanity-check the dataset loads
```

Set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) before running the labeler.

## Out of scope

Multi-user, durable storage, real auth, web UI, exhaustive quirk handling, production observability. Do not add these.

## Library docs

Use the **context7** MCP server (configured in `.mcp.json`) to fetch current docs for any library — anthropic SDK, pydantic, fastapi, etc. — before writing non-trivial library code. Prefer it over web search for API references.

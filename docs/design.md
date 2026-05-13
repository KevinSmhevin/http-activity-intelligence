# HTTP Activity Intelligence — Design

## Requirements and assumptions

The brief is to turn `data/http_events.jsonl` (5,101 events captured from one
laptop over ~17 hours) into a system that can answer three questions:

1. What were the distinct activity sessions in this period?
2. Which session had the most sustained focus, and which was the most fragmented?
3. What did the user spend the most time on?

...and produce a short, grounded LLM label for each session.

A few load-bearing assumptions I made. Each is a place a reasonable engineer
could land somewhere else.

- **"Session" means a user's engagement with an application, not an HTTP
  session.** Three Google Docs tabs on the same writing task are one session.
  A websocket reconnect is the same session. *What this gives up:* I can't
  separate two browser tabs that simultaneously visit different docs on the
  same apex — they look like one engagement.
- **"Most time on" is grouped by LLM label, with apex domain as fallback.**
  This is the query that most directly exercises the labeler's output. 
  *What this gives up:* a bad label poisons the breakdown. The fallback grouping
  bounds the damage but doesn't eliminate it.
- **Idle is a first-class interval.** Foreground gaps ≥ 20 min surface as
  named `IdleInterval` records so the timeline reflects "user was away"
  rather than pretending nothing happened. *What this gives up:* another
  threshold I have to defend.
- **Persistence is in-memory.** Events are loaded once at startup and held
  as a list; nothing is written to disk or a database. Full reasoning in the
  Data model section. *What this gives up:* the system can't survive a
  process restart and can't be queried by another tool.
- **Invocation is a Python class plus a thin CLI, not an HTTP service.** A
  FastAPI wrapper is an hour I'd rather spend on the labeler.

**Out of scope:** multi-user support, durable storage, auth, UI, exhaustive
quirk handling, production observability.

---

## Data model

Events are the immutable source of truth, held as a `list[Event]` inside a
small `Repository`. Sessions, idle intervals, fragmentation scores, focus
rankings, time breakdowns — everything else — are computed by pure functions
of `(events, config)` and exist only in the response. The one materialized
exception is the label cache, keyed by a hash of the session's compressed
content rather than its identity.

```python
class Repository:
    events: list[Event]   # immutable; source of truth

sessionize(events, cfg)  -> list[Session]
detect_idle(events, cfg) -> list[IdleInterval]
```

**Why:** Sessionization parameters (gap threshold, idle cutoff, engagement
key) are exactly the rules I expect to tune during iteration. Keeping
sessions derived means changing a rule is free of drift risk — there's no
stored state to fall out of sync with the events. The dataset is small
enough that recomputing per request is milliseconds.

**Tradeoff:** Sessions have no stable identity across runs. A consumer
can't bookmark "session X" by URL or attach a human-curated label that
overrides the LLM without materializing sessions and assigning IDs. At one
user-day I take the simplicity; at scale I'd graduate.

**Why not persist to disk or a database.** The main reason is scope: the
labeler and sessionizer are the surfaces the brief weights heavily, and
those got the time. An ORM, schema, and migration layer is at least an
hour of plumbing I'd rather have spent on grounding edge cases and tuning
sessionization heuristics. The supporting facts at this size cooperate —
the dataset is 1.4 MB and parses in milliseconds, the system is
LLM-latency-bound not I/O-bound, and persisting *derived* sessions would
go stale against the sessionization parameters I most expect to tune
(gap threshold, idle cutoff, engagement-key definition), forcing a
rebuild step. *Cost:* the system can't survive a process restart and
can't be queried by another tool. Both unlock real value at scale,
neither at one user-day.

**Alternative considered and rejected — materialized sessions with stable
IDs.** This is the *shape* decision, separate from the storage one above:
sessions exist as their own records with a `session_id`, events
foreign-keyed to them. The store could live in memory or on disk; the shape
is what matters. Buys stable session identity (external references, URL
bookmarking), and a place to attach per-session state that isn't derived
from events — most usefully, a human-curated label that overrides the LLM.
Rejected here because none of those benefits apply at one user-day:
nothing references sessions by URL, no human is curating labels, and
recompute on every query is milliseconds. The swap is a localized change
to `Repository` and the labeler's cache key, so deferring it costs little.

**Second alternative — time-series with symmetric interval annotations.**
Events as points, sessions and idle as symmetric intervals on a continuous
timeline. The right answer if the API grows toward "what was happening at
3pm?" or "what overlaps [t1,t2]?" queries. None of the three required
queries need interval-algebra, so paying for an interval tree (or
hand-rolling one) wasn't worth it now.

---

## Sessionization

The pipeline runs in five stages over the immutable event list:

1. **Normalize timestamps to UTC.** The source mixes `-07:00` and `Z` — 6
   UTC stragglers (terminal calls that crossed midnight PT), rest local.
2. **Dedupe.** 5 proxy retries removed via
   `(host, path, method, bytes_out, bytes_in)` matching within 2 seconds.
   Tiny effect, cheap to do.
3. **Classify foreground vs background.** Rule-based: long-poll / heartbeat
   / sync paths, `wss-*` and `realtime-*` host prefixes, analytics apex
   domains, app-with-no-tab heuristics for Dropbox/OneDrive. ~81% of events
   drop out. *Why rules over ML:* the noise is highly structured (one rule
   per host family), and a misclassification is fixable in five seconds.
   *Tradeoff:* the ruleset is brittle to new traffic shapes — adding a new
   chat app means editing `classify.py`.
4. **Time-gap split within each engagement.** Engagement key = apex domain
   for browser events, `source_app` otherwise. A new session starts whenever
   the foreground-event gap inside an engagement exceeds 5 minutes.
5. **Detect idle.** Foreground gaps ≥ 20 min on the *global* timeline
   become `IdleInterval` records, carrying the set of background apps still
   polling during that window — useful for telling "user away, laptop on"
   from "user away, laptop off."

**Why engagement key, not `tab_id`:** A session represents engagement with an
application, which may span many HTTP-level sessions. Grouping by `tab_id`
shatters that into per-tab fragments — three Google Docs tabs become three
sessions instead of one — and `tab_id` is null for ~41% of events anyway.
*Tradeoff:* I can no longer distinguish two browser tabs hitting different
paths on the same apex. The fragmentation metric below partially recovers
that signal.

**Why 5 min for the gap threshold:** Foreground inter-event gaps in this
dataset have p90 around 2 minutes and p99 around 2.3 minutes; globally the
*only* gap above 5 min is the one big idle window. Within an engagement
(where another engagement's activity interleaves), 5 min cleanly separates
distinct work episodes from sub-resource loads and ordinary navigation, with
margin. The threshold lives in `SessionConfig`.

**Why 20 min for idle:** Deliberately larger than the 5-min session gap, so a
brief lull during deep work doesn't trip the idle detector. The dataset has
exactly one gap above 20 min (~4.5 hours, 17:58 PT → 22:30 PT), which lines
up with the brief's note that the user was away from the laptop.

**Fragmentation = distinct `(apex_domain, tab_id)` pairs per minute of
session duration.** Low values = one host/tab dominates (deep work). High
values = rapid switching (research browsing, doomscrolling). Rejected two
alternatives: Shannon entropy of host counts (harder to explain to a
non-technical reader, not usefully bounded) and raw distinct-host count
(doesn't normalize by duration, so longer sessions score artificially high).
*Tradeoff:* the metric understates fragmentation *inside* an SPA — a
30-minute Notion session that hops between five pages still looks unified
because the apex doesn't change.

End-to-end on this dataset: **5,101 raw events → 983 foreground → 36
sessions + 1 idle interval.**

---

## LLM session labeling

Three invariants drive the design: the model sees only evidence drawn from
the session; every label is validated against that evidence before being
accepted; the system always produces *some* label for every session.

**Input compression.** Each session collapses into a fixed-shape summary of
~20–30 lines: `source_app`, duration, event count, top apex domains with
counts, top paths per apex, dominant referrers, fragmentation score. Sending
raw events is expensive and gives the model too much room to fixate on
noise.

**Prompt and structured output.** System message: label using only the
evidence provided, prefer short and concrete labels over generic ones, set
`confidence: low` when evidence is thin. User message: the compressed
summary. Output is forced through a tool-use schema:
`{label, confidence: low|medium|high, evidence: list[str]}`. `temperature=0`
for reproducibility.

*Why tool-use over free-text JSON:* removes an entire class of failure modes
(malformed JSON, model preambles, code-fence wrapping). *Tradeoff:* slightly
higher token cost and a model-specific dependency on the Anthropic SDK.

**Grounding.** Every entry in `evidence` is required to literally appear
(case-insensitive, with subdomain flexibility for hosts) in the compressed
input. Labels whose evidence fails the check are discarded as
hallucinations; the session retries once with a tightened prompt, then falls
back. This check is load-bearing — the model is fully capable of fabricating
plausible activity, and nothing else in the system prevents it. *Tradeoff:*
the check is mechanical: it catches fabricated hosts but not, say, an
overconfident interpretation of real evidence ("doomscrolling" when the user
spent 30 seconds on Twitter). The `confidence: low` instruction is the
partial mitigation.

**Failure modes and fallbacks.** Malformed structured output, hallucinated
evidence, empty label, network error — all funnel into one retry with a
stricter prompt, then a deterministic fallback. The fallback is
`"Activity on {dominant_apex_domain}"` with `confidence: low` and
`label_source: "fallback"` so downstream consumers can see provenance. Every
session leaves the pipeline with a non-null label.

**Cost and caching.** Labels are cached by SHA-256 of the compressed input,
not session ID. Two sessions with identical compressed content share a hit —
useful across recomputations at different sessionization parameters, and at
scale across users with identical activity patterns. A full run over 36
sessions on a Haiku-class model is in the cents.

**Large-session handling.** If a session's compressed summary exceeds the
token budget (none in this dataset, realistic at scale), it's truncated to
top-K hosts and a sampled subset of paths, with a `[truncated]` marker so
the model can lower its confidence rather than over-commit on partial
evidence.

---

## Scaling to thousands of users, continuously

The current shape is correct for one user-day. The pieces that break at
scale and how I'd change them:

- **In-memory events → durable append-only store.** Today the events list
  lives in process memory; at scale it needs to survive restarts and accept
  new events continuously. A reasonable default: Postgres (partitioned by
  date and `user_id`, indexed on `(user_id, timestamp)`) for the hot
  window, plus an object-store archive (S3 / GCS) for raw events older
  than ~30 days. "Append-only" here describes the access pattern — events
  are INSERTed, never UPDATEd or DELETEd — not a specialized DB engine.
  ClickHouse or TimescaleDB is the right swap if event volume gets high
  enough that Postgres struggles; Kafka in front of either is the right
  swap if you need true stream-processing semantics. Sessions become
  materialized rows with stable IDs, recomputed by a background worker on
  a tunable cadence — the relational shape I rejected at one user-day,
  now justified by the reasons that didn't exist at that size.
- **Batch sessionization → incremental.** Process events as they arrive;
  close out a session when a 5-min foreground gap is observed in the live
  stream. Today's batch sessionizer becomes the backfill / replay path.
- **Rule-based foreground classifier → learned classifier.** The ruleset
  won't survive thousands of users' app inventories. Train on a sampled
  labeled set; keep the rule fallback for safety.
- **Labeler runs async and batched, cache promoted to Redis.** Multiple
  sessions per API call, message-bus driven. At scale, most activity is
  repetitive across users (Slack on a channel, GitHub on a repo) so the
  content-hash cache becomes the dominant cost lever.
- **Modular packages → potentially separate services.** Sessionization
  and labeling are already separate modules inside
  `activity_intelligence/`, which is the cheap part of the decomposition.
  The bigger question at scale is whether they should be separate
  *services*. Their profiles diverge sharply: sessionization is
  CPU-bound, deterministic, with no external deps (milliseconds per
  session); the labeler is I/O-bound on third-party LLM calls (hundreds
  of ms to seconds, with retries, rate limits, and real per-call cost).
  Splitting buys **independent scaling** (a labeler bottleneck doesn't
  force me to scale sessionization with it), **independent failure
  modes** (Anthropic outage shouldn't take down the sessions endpoint),
  and **independent deploy cadence** (prompts iterate far faster than
  sessionization rules). Splitting costs operational complexity and an
  inter-service hop on the request path. The middle path I'd take first
  — same codebase, separate worker pools, labeler consuming
  "label-this-session" jobs from a queue — is implicit in the
  async/batched bullet above and captures most of the benefit. I'd
  promote to fully separate services only when metrics show one
  component clearly dominating cost, latency, or incident frequency.
  Don't need to opt in to microservices right away. 
- **Per-user isolation.** Repository keyed by user ID; everything else
  keeps shape.
- **CLI → FastAPI service.** Today the `ActivityIntelligence` class is
  invoked by a thin CLI; at scale it sits behind a FastAPI service so
  clients hit it over HTTP. FastAPI is the natural fit — it's async
  (matters because labeler calls are I/O-bound, so one worker can hold
  many concurrent requests), it uses Pydantic models (the `Event` /
  `Session` / `IdleInterval` models I built are already Pydantic, so
  request/response serialization is free), and it emits OpenAPI docs
  that downstream consumers can codegen clients against. Routes mirror
  the three required queries — `GET /users/{user_id}/sessions`,
  `.../focus-ranking`, `.../time-breakdown` — plus a webhook endpoint
  for streaming new events in, and a `PATCH /sessions/{id}/label`
  endpoint for the human-curated label overrides that the materialized-
  sessions shape now permits. Deployment is `uvicorn` or `gunicorn`
  behind a load balancer, horizontally scaled, with per-user auth (API
  keys or JWT) and rate limiting at the edge. The CLI stays around as
  an admin / backfill tool. This works cleanly because the Python-class
  invocation surface I picked at one user-day was deliberately designed
  to be wrappable — FastAPI is a thin shell over the same core, not a
  rewrite of it.
- **Test infrastructure.** Today's coverage is one unit test file (the
  foreground classifier) plus ad-hoc CLI runs against the single shipped
  dataset. At scale that becomes a real test pyramid. *Unit tests* on
  every pure function in `sessionizer`, `idle`, `classify`, and the
  labeler's grounding check — these are cheap because the functions are
  already pure and config-driven. *Integration tests* that run the full
  pipeline end-to-end against large synthesized fixture datasets,
  covering edge cases the one shipped dataset doesn't hit: timezone-
  straddling sessions, all-background users, dense multi-engagement
  interleaving, sessions that fail grounding twice and hit the
  fallback, sessions large enough to trigger summary truncation. *Labeler
  regression tests* with locked LLM responses replayed from a fixtures
  file (recorded once with real API calls, replayed thereafter) so prompt
  or compression-format changes catch regressions deterministically and
  without API cost. *Property tests* on invariants the system should
  hold for any input — total session time + idle time ≤ wall-clock span,
  every session leaves the pipeline with a non-null label, identical
  content-hashes return identical labels from the cache. The labeler
  regression tests are the most important of these; they're the only
  safe way to iterate on prompts once real users depend on label
  stability.
- **Observability.** Three layers, each answering a different question.
  *Metrics* (Prometheus + Grafana or Datadog) answer "is the system
  healthy right now?" — per-stage counters: events ingested, foreground
  rate, sessions emitted, label cache hit rate, fallback rate, LLM call
  latency. Today's `stats` command becomes a metrics endpoint, with
  alerts on regressions. *Structured logging* (Splunk, CloudWatch, or
  Loki) answers "why did *this* session get *this* label?" — one log
  line per pipeline stage carrying `user_id`, `session_id`, and the
  decision the stage made, queryable after the fact. Use a real logging
  library (Python `logging` with a JSON formatter, or `structlog`) so
  every line is structured rather than free-text. *Error tracking*
  (Sentry) answers "what's broken?" — LLM API failures, grounding
  validation failures with the offending evidence captured, worker
  crashes, ingest parse errors. The grounding-failure rate is the canary
  I'd watch most closely: a spike usually means the model has drifted or
  the compressed-summary format changed in a way the model can no longer
  ground against.

What doesn't change: the data model (immutable events + derived sessions),
the sessionization invariants, the grounding contract on the labeler.
Those are the load-bearing decisions.

---

## What I cut and why

- **HTTP service.** A FastAPI wrapper buys nothing the CLI doesn't already
  give a reviewer. The hour went into labeler grounding instead.
- **Cross-engagement semantic merging** (bundling several short related
  sessions into one "research session" via embedding clustering or topic
  graphs). Real value, but it needs a separate evaluation harness to know
  whether the clusters are sensible — out of budget. Fragmentation + per-
  engagement labels are the partial substitute.
- **Per-host path normalization beyond what `classify.py` already does.**
  Notion `saveTransactions` and Calendar `eventedit` are already collapsed
  in the source data; further URL cleaning would have been theater.
- **A learned foreground classifier.** Rules are good enough for one user;
  ML is the right move at thousands, not now.
- **Multi-provider LLM abstraction.** Anthropic-only. Adding an
  OpenAI/Gemini swap layer is half an hour I'd rather have spent on
  grounding edge cases.
- **Broader test coverage.** I tested foreground classification — the
  most rule-heavy and drift-prone piece, where a single misclassified
  host cascades into wrong sessions. Sessionization, idle detection, and
  labeling are integration-shaped and would have needed a few synthesized
  multi-engagement fixture datasets plus a locked-LLM-response fixtures
  file for replay-based labeler tests, none of which I had time to build
  well. The full test pyramid I'd build at scale is in the scaling
  section above.
- **Web UI.** Out of scope per the brief.

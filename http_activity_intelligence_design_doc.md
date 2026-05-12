# HTTP Activity Intelligence Design Doc

# Requirements & Assumptions

This take-home asks for an end-to-end system that turns raw HTTP capture
into meaningful intelligence about how a user spent their time online.
Three loosely-coupled deliverables: an ingestion/modeling layer, a query
interface, and an LLM-powered session labeler — plus this doc.

## What the system must do

1. **Ingest and model the events.** Read `http_events.jsonl`, choose a
   representation, and serve queries against it. The recruiter clarified
   that persistence does not need to be on disk — modeling choices and
   the alternatives considered matter more than durability.

2. **Answer three queries through an invocation surface:**
   - List the distinct activity sessions in the captured period.
   - Identify the most sustained-focus session and the most fragmented
     session. Both are *within-session* properties (confirmed): a
     session's internal scatter, not a ranking against other sessions.
   - Identify what the user spent the most cumulative time on. This is
     an aggregate over sessions, grouped by category (not a single
     session).

3. **Label each session via an LLM.** Labels are short, human-readable,
   strictly grounded in the session's contents, and robust to large or
   degenerate sessions.

## Key assumptions

**"Session" means a user's engagement with an application, not an HTTP
session.** A single engagement may span
multiple HTTP sessions (websocket reconnects, tab refreshes,
sub-navigation). For browser events, "application" maps to apex domain
(three Google Docs tabs = one engagement); for non-browser events, to
`source_app`.

**Time within a session is estimated from inter-event gaps, capped by an
idle threshold.** Adjacent events more than 5
minutes apart contribute no dwell time, preventing a long gap from
counting as continuous activity.

**Idle/away periods are first-class intervals on a continuous timeline,
not absences.** Surfacing idle as named intervals (≥20 min of no foreground activity)
makes the timeline complete and lets "what did the user spend most time
on?"

**Invocation is a Python class plus a thin CLI.** An HTTP
service was considered and cut — time was better spent on the labeler.

**"Most time on" groups sessions by their LLM-generated label**, with
apex domain as a fallback grouping. This is the query that most directly
exercises the labeler's output.

**Persistence is in-memory.** Events are an immutable list; sessions,
idle intervals, and per-session metrics are computed by pure functions
on demand. The LLM label cache is the one materialized exception, keyed
by a hash of the session's compressed content rather than session ID.

**Input data is intentionally messy.** Timezone mix, proxy duplicates,
nulls, background polling dominance, and at least one extended idle
period are documented quirks.

## Out of scope

Multi-user support; durable storage; real authentication; web UI;
exhaustive handling of every data quirk; production-grade observability.


## Data model

Events are the immutable source of truth, held as an in-memory list of
Pydantic `Event` records in a `Repository` class. All higher-order
concepts — sessions, idle intervals, per-session metrics, focus rankings,
time breakdowns — are computed by pure functions of `(events, config)`
and exist only as in-memory results during a request. The single
materialized exception is the LLM label cache, keyed by a hash of the
session's compressed content rather than its identity.

```python
class Repository:
    events: list[Event]                       # immutable, source of truth
    _by_engagement_key: dict[str, list[int]]  # lookup index, derived
    _by_apex_domain: dict[str, list[int]]     # lookup index, derived

sessionize(events, config)   -> list[Session]
detect_idle(events, config)  -> list[IdleInterval]
```

Each `Session` returned by `sessionize` is fully populated at construction
with its derived fields — duration, fragmentation score, dominant hosts,
source app. The function is deterministic: identical inputs produce
identical outputs and identical content hashes, so the label cache
survives recomputation cleanly.

This shape was chosen for three reasons specific to the brief. The
dataset is small enough that recomputing sessions per request takes
milliseconds, so there is no read-pattern benefit to storing them.
Persistence was explicitly de-prioritized by the recruiter in favor of
modeling judgment, and an immutable-events + derived-views model is the
cleanest expression of that judgment. Sessionization parameters (gap
threshold, engagement key, idle cutoff) are exactly the rules most
likely to be tuned during iteration; keeping sessions derived means
changing a rule is free of drift risk because there is no stored state
to fall out of sync with events.


## Sessionization

The pipeline runs in five stages over the immutable event list:
(1) normalize timestamps to UTC, since the source mixes `Z` and `-07:00`;
(2) dedupe events sharing `(host, path, method, bytes_out, bytes_in)`
within a 2-second window — these are proxy retries documented in the
brief;
(3) classify each event as foreground or background using path,
source-app, and apex-domain heuristics — long-poll, websocket
keepalives, CDN sub-resources, and analytics beacons all → background;
(4) within each *engagement* (apex domain for browser events,
source_app otherwise), sort foreground events by time and start a new
session whenever the gap between adjacent events exceeds 5 minutes;
(5) detect idle intervals as foreground gaps ≥ 20 minutes anywhere on
the global timeline.

```python
def sessionize(events, cfg) -> list[Session]:
    foreground = [e for e in events if e.is_foreground and not e.is_duplicate]
    by_engagement = group_by(foreground, engagement_key)
    sessions = []
    for group in by_engagement.values():
        sessions.extend(time_gap_split(group, cfg.gap_threshold))
    return sessions
```

**Engagement key, not tab_id.** The clarifications established that a
session represents a user's engagement with an application, which may
span multiple HTTP sessions — websocket reconnects, tab refreshes,
sub-navigation. Three Google Docs tabs are one engagement, not three; a
Slack WebSocket reconnect is the same engagement, not a new one. The
engagement key is therefore `apex_domain` for browser events and
`source_app` otherwise. Grouping by raw `tab_id` was considered first
and rejected — it shatters natural engagement into per-tab fragments,
degrades label coherence, and is closer to "HTTP session" than
"user-application engagement."

**Time-gap splitting within each engagement.** A 5-minute foreground gap
inside an engagement marks the boundary between sessions. The threshold
was chosen by inspecting inter-event gap distributions in the dataset:
gaps below 5 minutes were dominated by sub-resource loads and ordinary
navigation, while gaps above clearly separated distinct work episodes.
The value is exposed in `SessionConfig` so it can be tuned without
touching pipeline code.

**Fragmentation metric (within a session).** Defined as `distinct
(apex_domain, tab_id) pairs per minute of session duration`. Low values
indicate sustained focus — one host or tab dominates, as in a Google Doc
or a single repository view. High values indicate scatter — rapid host
or tab switching, characteristic of research browsing or doomscrolling.
The metric is intentionally within-session per the clarifications. Two
alternatives were rejected: Shannon entropy of host counts (harder to
defend to a non-technical reader, and not bounded usefully), and a raw
distinct-host count (doesn't normalize by duration, so longer sessions
score artificially high).

**Idle intervals are cross-engagement.** Sessionization breaks *within*
an engagement; idle detection looks *across* the global timeline. Any
foreground gap ≥ 20 minutes is surfaced as a named `IdleInterval`
carrying the set of background apps still polling during that window —
useful signal for distinguishing "user away, laptop on" from "user away,
laptop off." The 20-minute threshold is deliberately larger than the
5-minute intra-session gap, so brief lulls within deep work don't
fragment a session or trip the idle detector.

**What this approach deliberately omits.** Cross-engagement semantic
merging — bundling several short sessions on related topics into a
single research session — would require embedding-based clustering or a
graph model, both rejected on scope. The fragmentation metric and the
labeler's per-engagement summaries are the partial substitute.


## LLM session labeling

Each session is summarized into a compressed structured input and passed
to a cheap, deterministic model that returns a grounded structured
label. The pipeline is built around three invariants: the model sees
only evidence drawn from the session, every label is validated against
that evidence before being accepted, and the system always produces
*some* label for every session — never a crash, never a missing field.

### Input compression

Sending raw events is expensive and gives the model too much room to
fixate on noise. Each session is compressed into a fixed-shape summary:
`source_app`, duration, event count, top N hosts with counts, top M
paths per host, dominant referrers, and the fragmentation score. The
compressed form is roughly 20–30 lines of text — small enough to fit
several sessions per request at scale, dense enough to characterize
what the user was doing.

### Prompt strategy

The system message instructs the model to label the session using only
the evidence provided, to prefer short and concrete labels over generic
ones, and to return `confidence: low` whenever the evidence is
ambiguous. The user message is the compressed summary. The model
returns JSON of shape `{label: str, confidence: "low" | "medium" |
"high", evidence: list[str]}`, where each entry in `evidence` must cite
a host, path, or app from the input. Structured output is enforced via
the SDK's tool-use schema, eliminating an entire class of free-text
parsing failures. `temperature=0` makes the output reproducible across
runs.

### Grounding

After the model responds, every entry in `evidence` is validated to
literally appear (case-insensitively, with subdomain flexibility for
hosts) in the compressed input string. Labels whose evidence fails
validation are discarded as hallucinations; the session is retried
once with a tightened system prompt, and on second failure assigned
the deterministic fallback. This validation step is the load-bearing
piece of the grounding strategy — the model is technically capable of
fabricating plausible activity, and nothing else in the system
prevents it.

### Failure modes and fallbacks

Four failure modes are handled explicitly:

- **Malformed structured output** — one retry with a stricter prompt;
  on second failure, deterministic fallback.
- **Hallucinated evidence** — same path as above.
- **Refusal or empty label** — treated as deterministic-fallback.
- **Network or API error** — short backoff, one retry; on persistent
  failure, fallback applied and the session is marked
  `label_source: "fallback"` for downstream visibility.

The deterministic fallback is `"Activity on {dominant_apex_domain}"`
with `confidence: low`. Every session leaves the pipeline with a
non-null label and a known provenance.

### Cost and caching

Labels are cached by SHA-256 of the compressed input, not session ID.
Two sessions with identical compressed content share a cache hit —
useful across recomputations of sessionization with different
parameters, and at scale across users with identical activity patterns.
Cost at one user-day (50–80 sessions on a Haiku-class model) is on the
order of cents. The cache plus structured-output discipline mean a
full pipeline rerun produces identical labels at zero additional API
cost.

### Large-session handling

If a session's compressed summary exceeds the configured token budget
(rare on this dataset, realistic at scale), the summary is truncated to
top-K hosts and a sampled subset of paths, and the prompt is annotated
with a `[truncated]` marker so the model can lower its confidence
appropriately rather than over-committing on partial evidence.

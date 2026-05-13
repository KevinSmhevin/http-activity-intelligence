# HTTP Activity Intelligence — Take-Home Exercise

Welcome. Please read this whole document before you start.

## The problem

You're given `http_events.jsonl` — a log of HTTP requests captured from a single user's laptop over roughly 24 hours. Every outbound request from their browser and apps is in there: timestamps, hostnames, paths, methods, status codes, request and response sizes, the source app that made the request, and a few other fields documented below.

Build a system that turns this raw stream into something meaningful: a model that can answer questions about how the user spent their time online, and an LLM-powered layer that labels coherent activity sessions in human terms (e.g. "researching graph databases", "deep work on a design doc", "doomscrolling").

## What we want from you

1. **An ingestion + modeling layer.** Read the events, decide how to represent them, and persist that representation. The shape of the model is your call. We are *not* telling you to use a graph, a time-series, an event log, or anything else. Pick what fits the queries below and justify it.

2. **An API** that answers at least:
   - "What were the distinct activity sessions in this period?"
   - "Which session had the most sustained focus, and which was most fragmented?"
   - "What did the user spend the most time on?"

   Define and document the contract. No UI required.

3. **An LLM-powered session labeler.** For each activity session your system identifies, produce a short human-readable label. The label must be grounded in the session's actual contents, not hallucinated. How you define a "session," what context you give the model, how you handle large sessions, and how you keep it cheap and reliable — those are your design decisions.

4. **A design doc (1–2 pages)** covering:
   - The requirements as you understood them, and any assumptions you made
   - Your data model, and at least one alternative you considered and rejected
   - Your sessionization approach and why
   - Your LLM labeling design — prompt strategy, grounding, failure modes
   - What you'd change to scale this from one user / one day to thousands of users continuously
   - What you cut and why

## Time budget

**2–3 hours.** We mean it. If you find yourself building a fourth endpoint or polishing a schema, stop and write the design doc.

## Use of AI tools

You are encouraged to use Claude Code, Cursor, Copilot, or any other AI coding tool. We expect you to. As part of your submission, please include:

- The prompts or transcripts you used for non-trivial parts of the work (a summary or a few representative excerpts is fine — we don't need everything)
- Notes on places you accepted the AI's output, places you overrode it, and places you caught it being wrong

We care about *how* you work with these tools, not whether you use them.

## Before you start

You're welcome to ask clarifying questions. Email them to your interview contact before you start coding. We'll respond within a business day. Candidates who never ask anything are telling us something.

---

## Data: `http_events.jsonl`

One JSON object per line. Approximately 5,000 events spanning ~24 hours.

### Schema

| Field | Type | Description |
|---|---|---|
| `timestamp` | string | ISO 8601. Mostly with timezone offset (`-07:00`); a small number are in UTC (`Z` suffix). Watch out. |
| `method` | string | HTTP method (`GET`, `POST`, etc.) |
| `host` | string | Destination hostname |
| `path` | string | Request path. May be `null` in a few records. |
| `status_code` | integer or null | HTTP response status. May be `null` in a few records. |
| `bytes_out` | integer | Approximate request body size |
| `bytes_in` | integer or null | Approximate response body size. May be `null` in a few records. |
| `source_app` | string | Which app on the laptop made the request: `chrome`, `slack`, `dropbox`, `terminal`, etc. |
| `tab_id` | string or null | For browser events, an opaque identifier for the browser tab. `null` for non-browser apps. |
| `referrer` | string or null | The page that initiated the request, when known. `null` for many background and app-originated requests. |
| `client_ip` | string | The laptop's local IP at the time of the request. |

### Things you should know about this data

- It is messy in roughly the ways real captured logs are messy. Some of the mess is interesting signal; some is noise; figuring out which is part of the problem.
- A small number of events have null fields. A small number of events are duplicated (proxy retry). A small number of timestamps are serialized in UTC instead of local time.
- Background polling from chat and sync apps generates a large fraction of the raw event volume. Naive counts will be dominated by it.
- A single page load typically fires many sub-requests to CDNs and analytics endpoints. They are not separate "activities."
- The user's `client_ip` changes during the day — they moved between networks.
- There is at least one extended period with no foreground activity. The user was not at the laptop.

You do not have to handle every quirk perfectly. We're more interested in which quirks you notice, which you address, and which you consciously choose to ignore.

---

## Submitting

Send us a zip or a Git repo containing via email or the website:
- Your code
- Instructions to run it (assume we have Python 3.11+ or Node 20+ and an API key for whatever LLM provider you used)
- Your design doc (Markdown or PDF)
- Your AI-tool notes (transcript excerpts or a written summary)

If your code doesn't quite run end-to-end, that's okay — tell us where it breaks and what you'd do next. We'd rather see honest, partial work with clear thinking than something polished but shallow.

## How we'll evaluate

- **Requirement gathering:** What did you ask, assume, push back on?
- **Modeling judgment:** Did you pick a representation that actually fits the queries? Did you consider alternatives? Can you defend the choice?
- **Abstractions:** Could a teammate add a new event source (DNS logs, app focus events) without rewriting your core?
- **Agentic design:** Is the labeler grounded, bounded, resilient? Or is it `prompt = f"label this: {session}"`?
- **AI workflow:** How did you actually use these tools?
- **Scoping discipline:** What did you not build, and why?



Good luck.

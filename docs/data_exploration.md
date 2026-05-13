# data exploration

Exploration of `http_events.jsonl` before building the pipeline. Numbers below
are from `scratch.py` (deleted after this writeup); they should appear directly
in the design doc and unit tests as oracle values.

## Volume

- **5,101 total events** spanning **16.98 hours** (2025-10-14 07:00 PT → 23:58 PT).
  Not 24 h as the brief loosely says.
- `source_app`: dropbox 2043, slack 1653, chrome 1377, terminal 28 (matches CLAUDE.md).
- Three distinct `client_ip`s — 10.21.7.118 (2479), 192.168.1.42 (1930), 172.20.10.3 (692).
  User moved networks. Don't anchor identity here.

## Timestamps

- **6 events end in `Z`** (UTC); 5095 end in `-07:00`. All 6 UTC events are
  the `terminal` calls that crossed midnight PT (06:02 UTC the next day).
  Normalize all → UTC on ingest.

## Nulls

- `path`: **0 nulls** (CLAUDE.md says "a few" — wrong / outdated).
- `status_code`: **1 null**.
- `bytes_in`: **2 nulls**.
- `referrer`: 3,675 null (expected — most app traffic + many background calls).
- `tab_id`: 2,071 null (= non-chrome events; tracks exactly with non-browser apps).

## Duplicates (proxy retries)

- Same `(host, path, method, bytes_out, bytes_in)` within **2 s** → **5 duplicates**.
  All separated by 28–50 ms. Classic proxy retry signature. Drop the second copy.

## Background polling dominates

Refined heuristic (Slack WSS host, Dropbox longpoll, Slack `users.setPresence`,
analytics hosts, CDN asset hosts, `*.woff2/.svg/.webp/.css/.js` paths):

- **Background: 4,208 events (82.5%)**
- **Foreground (incl. gmail `/sync`): 893 events**
- After also tagging gmail `/sync/u/0/i/s` as background (303 events, all
  identical), **true foreground ≈ 590 events (~11.6%)**.

### What's noisy vs real

| Host | Events | Real? |
|---|---|---|
| client.dropbox.com | 2043 | 100% `longpoll` — background |
| wss-primary.slack.com | 1385 | 100% WSS keepalive — background |
| mail.google.com | 315 | **303 are `/sync/u/0/i/s` polls**; only 12 are thread reads `/u/0/#inbox/thread-*` |
| slack.com | 197 | 100% `/api/users.setPresence` — presence keepalive, background |
| www.notion.so | 224 | 177 `saveTransactions` autosaves + 47 `loadPageChunk` — foreground (driven by typing) |
| calendar.google.com | 122 | 100% identical path `/calendar/u/0/r/eventedit` — treat as foreground but path is useless for grounding |
| app.slack.com | 71 | 70 distinct `/client/T0001/C…` channels — clearly real user navigation |
| localhost | 28 | terminal `/api/v1/diagnose` calls — foreground |
| google.com `/search?q=…` | 37 | real searches: `cap+theorem`, `idempotency`, … |
| stackoverflow, github, linear, neo4j, ycombinator, reddit, twitter, ana.co.jp, booking, arxiv, martinfowler, youtube | ~90 total | real browsing, low volume but high label-signal |

## Inter-event gap distribution

### Global (all 5,101 events) — useless

- Max gap **31.99 s**. Dropbox/Slack polling fills every second, so the
  global timeline never gaps.
- This means **idle detection MUST run on the foreground stream**, not raw events.

### Foreground only (n=892 gaps)

- p50 **37.3 s**, p75 73 s, p90 119 s, p95 131 s, p99 138 s.
- Max **271.0 min** (single gap, 17:58:59 → 22:30:00 PT).
- **Foreground gaps > 5 min: 1.** Foreground gaps > 20 min: 1. Same gap.

→ This is the user-away period the brief promised. **Exactly one big idle
window**, ~4.5 h. The 20-min idle threshold in the design doc fires exactly
once, which is the right behavior.

→ The 5-min sessionization gap threshold also fires only once *globally*.
Within-engagement boundaries will be more numerous (different engagements
swap, so each one's "last event" is followed by a long gap), but sequentially
on the foreground timeline there's effectively one big break.

## Implications for sessionization

1. **Foreground filter is load-bearing.** Without it the entire dataset is one
   continuous blob — no gap > 32 s. Must classify foreground/background
   *before* gap-splitting.
2. **Dedupe is cheap.** Only 5 duplicate copies in 5,101 events. A simple
   `(host, path, method, bytes_out, bytes_in)` + 2 s window is sufficient.
3. **TZ normalization is cheap.** Only 6 UTC timestamps; rest are -07:00.
   Convert all to aware-UTC on ingest.
4. **`tab_id` is useless as engagement key.** 2,071 nulls (all non-browser),
   and 70 distinct `app.slack.com` paths each with their own implicit tab —
   the design doc's "apex domain / source_app" engagement key is correct.
5. **Path normalization is unnecessary.** Synthetic paths are already collapsed
   (one Notion page `a1b2c3d4e5f6`, one Calendar `/calendar/u/0/r/eventedit`).
   Don't waste time on URL cleaning.
6. **LLM evidence pool is small.** Foreground signal is concentrated on
   ~15 hosts; the compressed summary per session will be short and the
   "every evidence entry must literally appear" check is easy to satisfy.

## Specific numbers to cite in design doc

- 5,101 raw events → **~893 foreground** with refined heuristic
  (~590 if gmail `/sync` polls are filtered, which they should be).
- **82.5%** of events are background polling.
- **5 duplicate events** removed via 2-s same-shape window.
- **6 UTC timestamps** vs 5095 local — normalize on ingest.
- **One idle interval** detected with the 20-min cutoff: 17:58 → 22:30 PT,
  ~4 h 31 min.
- Three `client_ip`s observed (network roaming).

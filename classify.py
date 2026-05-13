from models import Event


BACKGROUND_PATH_SUBSTRINGS: tuple[str, ...] = (
    "/longpoll",
    "/poll",
    "/heartbeat",
    "/ping",
    "/events/subscribe",
    "/realtime",
    "/sync/",
    "setpresence",
)

BACKGROUND_HOST_PREFIXES: tuple[str, ...] = (
    "wss-",
    "realtime-",
    "edge-chat",
)

# Extend if Phase 1 data suggests more.
BACKGROUND_APEX_DOMAINS: frozenset[str] = frozenset({
    "google-analytics.com",
    "segment.io",
    "datadoghq.com",
    "sentry.io",
    "mixpanel.com",
    "doubleclick.net",
    "googletagmanager.com",
})

# Slack is intentionally excluded — its events carry tab_id="tab_slack" in
# this dataset, so the no-tab heuristic never fires for slack.
BACKGROUND_APPS_NO_TAB: frozenset[str] = frozenset({
    "dropbox",
    "onedrive",
})


def classify_foreground(event: Event) -> bool:
    path_lc = event.path.lower() if event.path is not None else None
    host_lc = event.host.lower()

    if path_lc is not None and any(s in path_lc for s in BACKGROUND_PATH_SUBSTRINGS):
        return False
    if any(host_lc.startswith(p) for p in BACKGROUND_HOST_PREFIXES):
        return False
    if event.apex_domain in BACKGROUND_APEX_DOMAINS:
        return False
    if event.source_app in BACKGROUND_APPS_NO_TAB and event.tab_id is None:
        return False
    return True

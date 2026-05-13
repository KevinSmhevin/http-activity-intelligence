from datetime import datetime, timezone

import pytest

from activity_intelligence.classify import classify_foreground
from activity_intelligence.models import Event


def make_event(
    *,
    host: str = "example.com",
    path: str | None = "/",
    source_app: str = "chrome",
    tab_id: str | None = "t1",
    apex_domain: str | None = None,
) -> Event:
    return Event(
        timestamp=datetime(2025, 10, 14, 12, 0, tzinfo=timezone.utc),
        method="GET",
        host=host,
        path=path,
        status_code=200,
        bytes_out=0,
        bytes_in=0,
        source_app=source_app,
        tab_id=tab_id,
        referrer=None,
        client_ip="10.0.0.1",
        apex_domain=apex_domain if apex_domain is not None else host,
        engagement_key=host if source_app == "chrome" else source_app,
        is_foreground=True,
        is_duplicate=False,
    )


BACKGROUND_CASES = [
    pytest.param(
        make_event(
            host="wss-primary.slack.com", path="/?token=x", source_app="slack", tab_id="tab_slack"
        ),
        id="slack-wss-host-prefix",
    ),
    pytest.param(
        make_event(
            host="WSS-PRIMARY.SLACK.com", path="/?token=x", source_app="slack", tab_id="tab_slack"
        ),
        id="wss-host-prefix-uppercase",
    ),
    pytest.param(
        make_event(host="example.com", path="/api/users.setPresence"),
        id="setpresence-mixed-case-path",
    ),
    pytest.param(
        make_event(host="realtime-events.example.com", path="/feed"),
        id="realtime-host-prefix",
    ),
    pytest.param(
        make_event(host="edge-chat.example.com", path="/x"),
        id="edge-chat-host-prefix",
    ),
    pytest.param(
        make_event(
            host="client.dropbox.com",
            path="/2/files/list_folder/longpoll",
            source_app="dropbox",
            tab_id=None,
        ),
        id="dropbox-longpoll-path-and-apps-no-tab",
    ),
    pytest.param(
        make_event(path="/api/poll/something"),
        id="poll-substring",
    ),
    pytest.param(
        make_event(path="/internal/heartbeat"),
        id="heartbeat-substring",
    ),
    pytest.param(
        make_event(path="/v1/events/subscribe"),
        id="events-subscribe-substring",
    ),
    pytest.param(
        make_event(path="/api/realtime/feed"),
        id="realtime-path-substring",
    ),
    pytest.param(
        make_event(host="api.mixpanel.com", apex_domain="mixpanel.com", path="/track"),
        id="mixpanel-apex",
    ),
    pytest.param(
        make_event(host="sentry.io", apex_domain="sentry.io", path="/api/1/envelope/"),
        id="sentry-apex",
    ),
    pytest.param(
        make_event(host="api.segment.io", apex_domain="segment.io", path="/v1/t"),
        id="segment-apex",
    ),
    pytest.param(
        make_event(
            host="stats.g.doubleclick.net", apex_domain="doubleclick.net", path="/r/collect"
        ),
        id="doubleclick-apex",
    ),
    pytest.param(
        make_event(
            host="www.google-analytics.com",
            apex_domain="google-analytics.com",
            path="/collect",
        ),
        id="ga-apex",
    ),
    pytest.param(
        make_event(
            host="slack.com", path="/api/users.setPresence", source_app="slack", tab_id="tab_slack"
        ),
        id="slack-presence-path-substring",
    ),
    pytest.param(
        make_event(
            host="mail.google.com",
            path="/sync/u/0/i/s",
            apex_domain="google.com",
        ),
        id="gmail-sync-path-substring",
    ),
    pytest.param(
        make_event(host="any.dropbox.host", path="/anything", source_app="dropbox", tab_id=None),
        id="dropbox-no-tab",
    ),
    pytest.param(
        make_event(host="onedrive.live.com", path="/x", source_app="onedrive", tab_id=None),
        id="onedrive-no-tab",
    ),
]


FOREGROUND_CASES = [
    pytest.param(
        make_event(host="www.notion.so", path="/api/v3/saveTransactions", apex_domain="notion.so"),
        id="notion-real-edit",
    ),
    pytest.param(
        make_event(
            host="mail.google.com",
            path="/u/0/#inbox/thread-1627",
            apex_domain="google.com",
        ),
        id="gmail-real-thread-read",
    ),
    pytest.param(
        make_event(
            host="calendar.google.com",
            path="/calendar/u/0/r/eventedit",
            apex_domain="google.com",
        ),
        id="calendar-real-eventedit",
    ),
    pytest.param(
        make_event(host="localhost", path="/api/v1/diagnose", source_app="terminal", tab_id=None),
        id="terminal-real-rpc-no-tab",
    ),
    pytest.param(
        make_event(host="github.com", path="/some/repo", apex_domain="github.com"),
        id="github-real-browse",
    ),
    pytest.param(
        make_event(
            host="stackoverflow.com",
            path="/questions/12345",
            apex_domain="stackoverflow.com",
        ),
        id="stackoverflow-real-question",
    ),
    pytest.param(
        make_event(
            host="app.slack.com",
            path="/client/T0001/C123",
            source_app="slack",
            tab_id="tab_slack",
        ),
        id="slack-real-channel-view",
    ),
    pytest.param(
        make_event(host="example.com", path=None),
        id="null-path-not-background",
    ),
    pytest.param(
        make_event(host="example.com", path=""),
        id="empty-path-not-background",
    ),
]


@pytest.mark.parametrize("event", BACKGROUND_CASES)
def test_classified_as_background(event: Event) -> None:
    assert classify_foreground(event) is False


@pytest.mark.parametrize("event", FOREGROUND_CASES)
def test_classified_as_foreground(event: Event) -> None:
    assert classify_foreground(event) is True

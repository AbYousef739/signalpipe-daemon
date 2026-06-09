"""Offline unit tests — pure stdlib, no network, no requests/praw/tweepy.

Deliberately imports only sse, senders, and config so the suite runs on a base
checkout with zero third-party deps installed.

    python tests/test_daemon.py        # plain runner
    python -m pytest tests/            # also works
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signalpipe_daemon.config import Config
from signalpipe_daemon.senders import Senders, _classify_error, _strip_u
from signalpipe_daemon.sse import parse_sse


def test_parse_sse():
    lines = [
        ": keep-alive ping",
        "event: connected",
        'data: {"auto_threshold": 1.01, "heartbeat_seconds": 30}',
        "",
        "event: mission_ready",
        'data: {"payload": {"id": "m1", "outreach_channel": "manual"}}',
        "",
        "event: heartbeat",
        'data: {"paused": false}',
        "",
    ]
    frames = list(parse_sse(lines))
    assert frames[0][0] == "connected"
    assert frames[0][1]["auto_threshold"] == 1.01
    assert frames[1][0] == "mission_ready"
    assert frames[1][1]["payload"]["id"] == "m1"
    assert frames[2][0] == "heartbeat"
    assert frames[2][1]["paused"] is False


def test_parse_sse_malformed_json():
    frames = list(parse_sse(["data: not json", ""]))
    assert frames[0][1] == {"_raw": "not json"}


def test_parse_sse_multiline_data():
    frames = list(parse_sse(['data: {"a":', 'data: 1}', ""]))
    assert frames[0][1] == {"a": 1}


def test_classify_error():
    assert _classify_error("429 Too Many Requests") == "rate_limited"
    assert _classify_error("RATELIMIT: try again later") == "rate_limited"
    assert _classify_error("403 Forbidden") == "banned"
    assert _classify_error("account suspended") == "banned"
    assert _classify_error("connection reset by peer") == "unknown"


def test_strip_u():
    assert _strip_u("u/spez") == "spez"
    assert _strip_u("/u/spez") == "spez"
    assert _strip_u("spez") == "spez"
    assert _strip_u("umbrella") == "umbrella"  # not eaten by a naive lstrip


def _cfg(**kw):
    base = dict(api_url="https://x", key="k")
    base.update(kw)
    return Config(**base)


def _x_creds(**kw):
    return _cfg(x_api_key="a", x_api_secret="b",
                x_access_token="c", x_access_secret="d", **kw)


def test_dispatch_manual_skips():
    r = Senders(_cfg()).send({"id": "m1", "outreach_channel": "manual",
                              "draft_content": "hi"})
    assert r.is_skip and not r.sent


def test_dispatch_empty_draft_fails():
    r = Senders(_x_creds()).send({"id": "m1", "outreach_channel": "twitter_reply",
                                  "draft_content": "   "})
    assert r.outcome == "failed" and r.error_class == "config"


def test_dispatch_unknown_channel_fails():
    r = Senders(_cfg()).send({"id": "m1", "outreach_channel": "carrier_pigeon",
                              "draft_content": "hi"})
    assert r.outcome == "failed"


def test_dispatch_twitter_dry_run():
    r = Senders(_x_creds()).send(
        {"id": "m1", "outreach_channel": "twitter_reply",
         "draft_content": "hello",
         "target": {"url": "https://x.com/u/status/12345"}},
        dry_run=True)
    assert r.outcome == "success"
    assert r.sent is False  # dry-run never hits the API


def test_dispatch_twitter_no_creds_fails():
    r = Senders(_cfg()).send(
        {"id": "m1", "outreach_channel": "twitter_reply",
         "draft_content": "hello",
         "target": {"url": "https://x.com/u/status/12345"}},
        dry_run=True)
    assert r.outcome == "failed" and r.error_class == "config"


def test_dispatch_twitter_bad_url_fails():
    r = Senders(_x_creds()).send(
        {"id": "m1", "outreach_channel": "twitter_reply",
         "draft_content": "hello",
         "target": {"url": "https://x.com/u/no-numeric-id/"}},
        dry_run=True)
    assert r.outcome == "failed" and r.error_class == "config"


def test_dispatch_twitter_cap_skips():
    r = Senders(_x_creds(max_twitter_per_day=0)).send(
        {"id": "m1", "outreach_channel": "twitter_reply",
         "draft_content": "hello",
         "target": {"url": "https://x.com/u/status/12345"}},
        dry_run=True)
    assert r.is_skip


def test_dispatch_reddit_comment_dry_run():
    cfg = _cfg(reddit_client_id="i", reddit_client_secret="s",
               reddit_username="u", reddit_password="p")
    r = Senders(cfg).send(
        {"id": "m1", "outreach_channel": "reddit_comment",
         "draft_content": "hello",
         "target": {"url": "https://reddit.com/r/x/comments/abc/post/"}},
        dry_run=True)
    assert r.outcome == "success" and r.sent is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nall {len(tests)} tests passed")

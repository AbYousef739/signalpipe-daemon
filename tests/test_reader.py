"""Tests for client-side reading (signalpipe_daemon.reader). No network.

    python tests/test_reader.py
    python -m pytest tests/            # also works
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from signalpipe_daemon import reader                              # noqa: E402
from signalpipe_daemon.client import AuthError                    # noqa: E402

REDDIT = "https://www.reddit.com/r/smallbusiness/new/.rss"
FORUM = "https://forum.example.com/latest.rss"
HN = "https://hnrss.org/newest?q=help+desk"


def _entry(i, **extra):
    e = {"link": f"https://www.reddit.com/r/x/comments/{i}/p/", "title": f"post {i}",
         "summary": f"body {i}", "author": f"/u/user{i}",
         "published_parsed": (2026, 9, 25, 9, i, 0, 3, 268, 0)}
    e.update(extra)
    return e


class _Client:
    def __init__(self, stations, ingest_reply=None, auth_fail=False):
        self.stations, self.ingested = stations, []
        self.reply = ingest_reply or (lambda sid, entries: {"status": "accepted", "entries": len(entries)})
        self.auth_fail = auth_fail

    def list_stations(self):
        if self.auth_fail:
            raise AuthError("operator key rejected (401)")
        return self.stations

    def ingest(self, station_id, entries):
        self.ingested.append((station_id, entries))
        return self.reply(station_id, entries)


def _stations():
    return [
        {"id": "s1", "name": "r/smallbusiness", "rss_url": REDDIT, "read_by": "client", "active": True},
        {"id": "s2", "name": "HN", "rss_url": HN, "read_by": "server", "active": True},
        {"id": "s3", "name": "forum", "rss_url": FORUM, "read_by": "client", "active": True},
        {"id": "s4", "name": "paused", "rss_url": FORUM, "read_by": "client", "active": False},
    ]


def test_entries_from_feed_keeps_what_the_brain_reads():
    feed = {"entries": [
        _entry(1),
        _entry(2, summary="", content=[{"value": "from content"}]),
        _entry(3, author="", author_detail={"name": "detail-name"}),
        {"title": "no link"},
    ]}
    out = reader.entries_from_feed(feed)
    assert [e["title"] for e in out] == ["post 1", "post 2", "post 3"]
    assert out[0] == {"link": "https://www.reddit.com/r/x/comments/1/p/", "title": "post 1",
                      "summary": "body 1", "author": "/u/user1", "published": "2026-09-25T09:01:00Z"}
    assert out[1]["summary"] == "from content"
    assert out[2]["author"] == "detail-name"


def test_entries_from_feed_caps_a_page_at_fifty():
    assert len(reader.entries_from_feed({"entries": [_entry(i) for i in range(80)]})) == 50


def test_only_active_client_stations_are_read():
    assert [s["id"] for s in reader.client_stations(_stations())] == ["s1", "s3"]


def test_read_once_fetches_client_stations_and_sends_each_page():
    fetched, slept, logs = [], [], []

    def fetch(url, agent=None):
        fetched.append((url, agent))
        return {"entries": [_entry(1), _entry(2)]}

    client = _Client(_stations())
    counts = reader.read_once(client, fetch=fetch, sleep=slept.append, log=logs.append)
    assert [u for u, _ in fetched] == [REDDIT, FORUM]                 # never the server's HN feed
    assert all(a.startswith("signalpipe-daemon/") for _, a in fetched)
    assert slept == [reader.FEED_DELAY_S]                             # a pause between the two feeds
    assert [sid for sid, _ in client.ingested] == ["s1", "s3"]
    assert client.ingested[0][1][0]["published"] == "2026-09-25T09:01:00Z"
    assert counts == {"stations": 2, "sent": 2, "entries": 4, "empty": 0, "skipped": 0, "errors": 0}


def test_read_once_counts_empty_feeds_skips_and_errors_and_carries_on():
    def fetch(url, agent=None):
        if url == REDDIT:
            return {"entries": []}
        raise RuntimeError("timed out")

    client = _Client(_stations())
    counts = reader.read_once(client, fetch=fetch, sleep=lambda s: None, log=lambda m: None)
    assert counts["empty"] == 1 and counts["errors"] == 1 and client.ingested == []

    cooled = _Client(_stations(), ingest_reply=lambda sid, e: {"status": "skipped", "reason": "cooldown", "retry_after_s": 120})
    logs = []
    counts = reader.read_once(cooled, fetch=lambda u, agent=None: {"entries": [_entry(1)]},
                              sleep=lambda s: None, log=logs.append)
    assert counts["skipped"] == 2 and counts["sent"] == 0
    assert any("cooldown" in m and "120s" in m for m in logs)


def test_nothing_marked_for_this_machine_means_nothing_fetched():
    fetched = []
    only_server = [s for s in _stations() if s["read_by"] == "server"]
    counts = reader.read_once(_Client(only_server), fetch=lambda u, agent=None: fetched.append(u),
                              sleep=lambda s: None, log=lambda m: None)
    assert counts["stations"] == 0 and fetched == []


def test_a_rejected_key_ends_the_reader_with_exit_code_2():
    assert reader.run_reader(_Client([], auth_fail=True), once=True, log=lambda m: None) == 2


def test_one_pass_exits_cleanly():
    original = reader.read_once
    reader.read_once = lambda client, log=print: {"stations": 0, "sent": 0, "entries": 0, "empty": 0, "skipped": 0, "errors": 0}
    try:
        assert reader.run_reader(_Client([]), once=True, log=lambda m: None) == 0
    finally:
        reader.read_once = original


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")

"""Tests for `signalpipe-daemon preview` (signalpipe_daemon.reader.preview). No network.

    python tests/test_preview.py
    python -m pytest tests/            # also works
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from signalpipe_daemon import reader                              # noqa: E402
from signalpipe_daemon.client import AuthError                    # noqa: E402

URL = "https://forum.example.com/latest.rss"
VERDICT = {"verdict": "VIABLE", "explanation": "Real buyers post here. Worth adding.",
           "feed": {"entries_read": 2, "fresh": 2}, "judged": 2, "kept": 1, "judgements_spent": 2,
           "sample": [{"title": "Need a help desk", "verdict": "kept"},
                      {"title": "Tips?", "verdict": "rejected"}]}


class _Client:
    def __init__(self, reply=None, auth_fail=False, error=None):
        self.calls, self.reply, self.auth_fail, self.error = [], reply or VERDICT, auth_fail, error

    def preview_station(self, product_id, *, entries=None, rss_url=None, sample=None):
        self.calls.append({"product_id": product_id, "entries": entries, "rss_url": rss_url, "sample": sample})
        if self.auth_fail:
            raise AuthError("operator key rejected (401)")
        if self.error:
            raise RuntimeError(self.error)
        return self.reply


def _feed(*_a, **_k):
    return {"entries": [
        {"link": "https://forum.example.com/t/1", "title": "Need a help desk", "summary": "40 agents",
         "published_parsed": (2026, 9, 25, 9, 0, 0, 3, 268, 0)},
        {"link": "https://forum.example.com/t/2", "title": "Tips?"},
    ]}


def test_preview_reads_here_and_sends_the_posts():
    client, logs = _Client(), []
    code = reader.preview(client, "p1", URL, sample=6, fetch=_feed, log=logs.append)
    assert code == 0
    call = client.calls[0]
    assert call["product_id"] == "p1" and call["sample"] == 6 and call["rss_url"] is None
    assert [e["link"] for e in call["entries"]] == ["https://forum.example.com/t/1", "https://forum.example.com/t/2"]
    assert call["entries"][0]["published"] == "2026-09-25T09:00:00Z"
    assert any("VIABLE" in m for m in logs)
    assert any(m.strip().startswith("KEPT") and "Need a help desk" in m for m in logs)


def test_preview_falls_back_to_the_brain_when_the_feed_cannot_be_read_here():
    def broken(*_a, **_k):
        raise OSError("connection refused")
    client, logs = _Client(), []
    assert reader.preview(client, "p1", URL, fetch=broken, log=logs.append) == 0
    assert client.calls[0]["entries"] is None and client.calls[0]["rss_url"] == URL
    assert any("asking SignalPipe to fetch it" in m for m in logs)

    client = _Client()
    assert reader.preview(client, "p1", URL, fetch=lambda *a, **k: {"entries": []}, log=lambda m: None) == 0
    assert client.calls[0]["rss_url"] == URL


def test_preview_exit_codes():
    assert reader.preview(_Client(auth_fail=True), "p1", URL, fetch=_feed, log=lambda m: None) == 2
    logs = []
    assert reader.preview(_Client(error="preview refused (409): read on your machine"), "p1", URL,
                          fetch=_feed, log=logs.append) == 1
    assert any("409" in m for m in logs)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")

"""Client-side reading: read your feeds on this machine, let the brain judge them.

The brain marks some of your stations ``read_by: "client"``. Those feeds are
never fetched by SignalPipe's servers; this reader fetches them from your
machine, the same way the scout would (at most 50 posts per feed, a pause
between feeds), and hands each page to ``POST /scout/ingest``. The brain then
scores the posts exactly as if its own scout had read them: same dedup, gates,
judges and missions, which reach your queue and the send stream as usual.

    pip install "signalpipe-daemon[reader]"
    signalpipe-daemon read            # every 30 minutes, until Ctrl-C
    signalpipe-daemon read --once     # one pass, for cron
    signalpipe-daemon preview --product <id> --url <feed>   # check a feed first
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from . import __version__

DEFAULT_INTERVAL_S = 1800        # the scout's own cadence
FEED_DELAY_S = 5                 # pause between feeds, as the scout does
MAX_ENTRIES = 50                 # one feed page; the brain accepts up to 50
USER_AGENT = (f"signalpipe-daemon/{__version__} "
              "(+https://github.com/AbYousef739/signalpipe-daemon)")


def _get(entry, key, default=None):
    """feedparser entries answer both .get() and attribute access."""
    if isinstance(entry, dict) or hasattr(entry, "get"):
        try:
            return entry.get(key, default)
        except TypeError:
            pass
    return getattr(entry, key, default)


def _iso(struct) -> Optional[str]:
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def entries_from_feed(parsed, limit: int = MAX_ENTRIES) -> list:
    """The fields the brain reads, from a feedparser result."""
    out = []
    for e in list(_get(parsed, "entries", []) or [])[:limit]:
        link = (_get(e, "link", "") or "").strip()
        if not link:
            continue
        summary = _get(e, "summary", "") or ""
        if not summary:
            content = _get(e, "content", None) or []
            if content:
                summary = _get(content[0], "value", "") or ""
        author = _get(e, "author", "") or (_get(_get(e, "author_detail", None) or {}, "name", "") or "")
        out.append({
            "link": link,
            "title": _get(e, "title", "") or "",
            "summary": summary,
            "author": author,
            "published": _iso(_get(e, "published_parsed", None) or _get(e, "updated_parsed", None)),
        })
    return out


def client_stations(stations: Iterable[dict]) -> list:
    """The stations the brain marks for this machine to read."""
    return [s for s in stations if s.get("read_by") == "client" and s.get("active", True)]


def read_once(client, *, fetch: Optional[Callable] = None,
              sleep: Callable[[float], None] = time.sleep,
              log: Callable[[str], None] = print) -> dict:
    """Read every client-side station once. Returns counts for the log."""
    # The station list comes first: a rejected key or "nothing to read" needs no
    # feed library, so a machine without feedparser can still run a clean pass.
    stations = client_stations(client.list_stations())
    counts = {"stations": len(stations), "sent": 0, "entries": 0, "empty": 0, "skipped": 0, "errors": 0}
    if not stations:
        log("reader: no stations are marked for this machine (read_by=client); nothing to do.")
        return counts
    if fetch is None:
        try:
            import feedparser  # extra: pip install "signalpipe-daemon[reader]"
        except ImportError as e:  # pragma: no cover - exercised by users, not tests
            raise SystemExit('feedparser is not installed: pip install "signalpipe-daemon[reader]"') from e
        fetch = feedparser.parse

    for i, station in enumerate(stations):
        if i and FEED_DELAY_S:
            sleep(FEED_DELAY_S)
        name = station.get("name") or station.get("id")
        try:
            entries = entries_from_feed(fetch(station["rss_url"], agent=USER_AGENT))
            if not entries:
                counts["empty"] += 1
                log(f"reader: {name}: the feed returned no posts")
                continue
            result = client.ingest(station["id"], entries)
            status = result.get("status")
            if status == "accepted":
                counts["sent"] += 1
                counts["entries"] += int(result.get("entries") or 0)
                log(f"reader: {name}: {result.get('entries')} posts sent for judging")
            else:
                counts["skipped"] += 1
                reason = result.get("reason", status)
                after = result.get("retry_after_s")
                log(f"reader: {name}: skipped ({reason}{f', retry in {after}s' if after else ''})")
        except Exception as e:  # noqa: BLE001 - one bad feed must not stop the pass
            counts["errors"] += 1
            log(f"reader: {name}: {e}")
    return counts


def run_reader(client, *, interval_s: int = DEFAULT_INTERVAL_S, once: bool = False,
               log: Callable[[str], None] = print) -> int:
    """Read on a loop (or once). Exit 0; 2 if the key is rejected; 1 if a
    one-off pass could not reach the brain."""
    from .client import AuthError
    while True:
        try:
            counts = read_once(client, log=log)
            log(f"reader: pass done: {counts['sent']} of {counts['stations']} feeds sent, "
                f"{counts['entries']} posts, {counts['skipped']} skipped, {counts['errors']} errors")
        except AuthError:
            log("reader: operator key rejected (401).")
            return 2
        except Exception as e:  # noqa: BLE001 - network or server trouble: log, retry next pass
            log(f"reader: pass failed: {e}")
            if once:
                return 1
            time.sleep(max(60, int(interval_s)))
            continue
        if once:
            return 0
        time.sleep(max(60, int(interval_s)))


def preview(client, product_id: str, url: str, *, sample: Optional[int] = None,
            fetch: Optional[Callable] = None, log: Callable[[str], None] = print) -> int:
    """Check a feed for buyers before adding it as a station. Saves nothing.

    The feed is read on this machine (like ``read``) and its posts are sent to
    ``POST /stations/preview``, where the brain scores them and its panel judges
    the best-matching ones. If this machine cannot read the feed, the URL is
    passed to the brain instead. Exit 0 with a verdict; 2 if the key is
    rejected; 1 if the preview could not run.
    """
    from .client import AuthError
    entries, local_error = [], None
    try:
        if fetch is None:
            import feedparser  # extra: pip install "signalpipe-daemon[reader]"
            fetch = feedparser.parse
        entries = entries_from_feed(fetch(url, agent=USER_AGENT))
        if not entries:
            local_error = "the feed returned no posts"
    except ImportError:
        local_error = 'feedparser is not installed (pip install "signalpipe-daemon[reader]")'
    except Exception as e:  # noqa: BLE001 - fall back to the brain fetching it
        local_error = str(e)
    if local_error:
        log(f"preview: could not read the feed here ({local_error}); asking SignalPipe to fetch it.")
    try:
        result = client.preview_station(product_id, entries=entries or None,
                                        rss_url=None if entries else url, sample=sample)
    except AuthError:
        log("preview: operator key rejected (401).")
        return 2
    except Exception as e:  # noqa: BLE001
        log(f"preview: {e}")
        return 1
    log(f"preview: {result.get('verdict')}: {result.get('explanation')}")
    feed = result.get("feed") or {}
    log(f"preview: {feed.get('entries_read', 0)} posts read, {feed.get('fresh', 0)} fresh, "
        f"{result.get('judged', 0)} judged, {result.get('kept', 0)} kept "
        f"({result.get('judgements_spent', 0)} judgements)")
    for s in result.get("sample") or []:
        log(f"  {'KEPT    ' if s.get('verdict') == 'kept' else 'rejected'}  {s.get('title', '')[:90]}")
    if result.get("note"):
        log(f"preview: {result['note']}")
    return 0



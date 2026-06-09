"""Platform senders — Reddit (PRAW) and X/Twitter (tweepy), lazily imported.

This is the ONLY module that touches your platform credentials. praw and tweepy
are optional extras: a base install carries neither, and each client is imported
only when a mission for that channel actually arrives. So a Reddit-only operator
never needs tweepy on disk, and vice-versa.

Nothing here scores, drafts, or stores anything. A mission arrives pre-drafted
from the brain; we post the text with your creds and report the outcome.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from random import uniform
from typing import Optional

# Outcomes the brain understands, plus a local-only "skip" that is never acked.
_SUCCESS = "success"
_FAILED = "failed"
_SKIP = "skip"


@dataclass
class SendResult:
    outcome: str
    error_class: Optional[str] = None
    detail: Optional[str] = None
    sent: bool = False  # True only once we have actually hit the platform API

    @property
    def is_skip(self) -> bool:
        return self.outcome == _SKIP


def _classify_error(msg: str) -> str:
    """Map a platform exception string to the brain's error_class vocabulary.

    The brain pauses a tenant's stream on "banned" (1h) or "rate_limited" (5m);
    "unknown" is reported for the audit trail but triggers no backoff.
    """
    m = msg.lower()
    if "ratelimit" in m or "rate limit" in m or "429" in m or "too many" in m:
        return "rate_limited"
    if any(w in m for w in ("forbidden", "banned", "suspend", "403",
                            "401", "blocked", "not allowed")):
        return "banned"
    return "unknown"


def _strip_u(author: str) -> str:
    """Normalize a Reddit handle: 'u/spez' / '/u/spez' -> 'spez'.

    Uses prefix slicing, NOT str.lstrip — lstrip is character-set based and
    would eat a leading 'u' from a name like 'umbrella'.
    """
    a = author.strip()
    if a.startswith("/u/"):
        return a[3:]
    if a.startswith("u/"):
        return a[2:]
    return a


class Senders:
    """Holds the platform clients and per-day send counters.

    Clients are built on first use (lazy import of praw / tweepy) and cached for
    the life of the process. Counters reset at local midnight.
    """

    def __init__(self, config):
        self.config = config
        self._tw = None
        self._reddit = None
        self._day = time.localtime().tm_yday
        self._twitter_sent = 0
        self._reddit_dms_sent = 0
        self._reddit_comments_sent = 0

    # --- lazy clients -----------------------------------------------------
    def _twitter(self):
        if self._tw is None:
            import tweepy  # extra: pip install signalpipe-daemon[twitter]
            c = self.config
            self._tw = tweepy.Client(
                consumer_key=c.x_api_key,
                consumer_secret=c.x_api_secret,
                access_token=c.x_access_token,
                access_token_secret=c.x_access_secret,
            )
        return self._tw

    def _reddit_client(self):
        if self._reddit is None:
            import praw  # extra: pip install signalpipe-daemon[reddit]
            c = self.config
            self._reddit = praw.Reddit(
                client_id=c.reddit_client_id,
                client_secret=c.reddit_client_secret,
                username=c.reddit_username,
                password=c.reddit_password,
                user_agent=c.reddit_user_agent,
            )
        return self._reddit

    # --- daily caps -------------------------------------------------------
    def _reset_daily(self) -> None:
        today = time.localtime().tm_yday
        if today != self._day:
            self._day = today
            self._twitter_sent = 0
            self._reddit_dms_sent = 0
            self._reddit_comments_sent = 0

    # --- dispatch ---------------------------------------------------------
    def send(self, mission: dict, dry_run: bool = False) -> SendResult:
        """Post one mission's draft on its channel and return the outcome."""
        self._reset_daily()
        channel = mission.get("outreach_channel") or "manual"
        draft = (mission.get("draft_content") or "").strip()
        target = mission.get("target") or {}

        # "manual" = the brain flagged this for a human. Never auto-send; the
        # operator handles it through the dashboard/plugin.
        if channel == "manual":
            return SendResult(_SKIP, detail="manual channel — operator handles")

        if not draft:
            return SendResult(_FAILED, error_class="config",
                              detail="empty draft_content")

        if channel == "twitter_reply":
            return self._send_twitter(draft, target, dry_run)
        if channel == "reddit_comment":
            return self._send_reddit_comment(draft, target, dry_run)
        if channel == "reddit_dm":
            return self._send_reddit_dm(draft, target, dry_run)

        return SendResult(_FAILED, error_class="config",
                          detail=f"unknown channel '{channel}'")

    # --- per-channel ------------------------------------------------------
    def _send_twitter(self, draft, target, dry_run) -> SendResult:
        if not self.config.twitter_ready:
            return SendResult(_FAILED, error_class="config",
                              detail="X credentials not configured")
        if self._twitter_sent >= self.config.max_twitter_per_day:
            # Skip, not fail: the mission stays 'approved' and retries tomorrow.
            return SendResult(_SKIP, detail="daily twitter cap reached")

        url = (target.get("url") or "").rstrip("/")
        tweet_id = url.split("/")[-1] if url else ""
        if not tweet_id.isdigit():
            return SendResult(_FAILED, error_class="config",
                              detail=f"cannot parse tweet id from '{url}'")

        if dry_run:
            return SendResult(_SUCCESS, sent=False,
                              detail=f"[dry-run] reply to tweet {tweet_id}")
        try:
            self._twitter().create_tweet(text=draft,
                                         in_reply_to_tweet_id=tweet_id)
        except Exception as e:  # noqa: BLE001 — SDKs raise many exception types
            return SendResult(_FAILED, sent=True,
                              error_class=_classify_error(str(e)), detail=str(e))
        self._twitter_sent += 1
        time.sleep(uniform(30, 90))  # anti-spam pacing between sends
        return SendResult(_SUCCESS, sent=True, detail=f"replied to {tweet_id}")

    def _send_reddit_comment(self, draft, target, dry_run) -> SendResult:
        if not self.config.reddit_ready:
            return SendResult(_FAILED, error_class="config",
                              detail="Reddit credentials not configured")
        if self._reddit_comments_sent >= self.config.max_reddit_comments_per_day:
            return SendResult(_SKIP, detail="daily reddit-comment cap reached")

        url = (target.get("url") or "").strip()
        if not url:
            return SendResult(_FAILED, error_class="config",
                              detail="no target url for reddit_comment")

        if dry_run:
            return SendResult(_SUCCESS, sent=False,
                              detail=f"[dry-run] comment on {url}")
        try:
            self._reddit_client().submission(url=url).reply(draft)
        except Exception as e:  # noqa: BLE001
            return SendResult(_FAILED, sent=True,
                              error_class=_classify_error(str(e)), detail=str(e))
        self._reddit_comments_sent += 1
        time.sleep(uniform(30, 90))
        return SendResult(_SUCCESS, sent=True, detail=f"commented on {url}")

    def _send_reddit_dm(self, draft, target, dry_run) -> SendResult:
        if not self.config.reddit_ready:
            return SendResult(_FAILED, error_class="config",
                              detail="Reddit credentials not configured")
        if self._reddit_dms_sent >= self.config.max_reddit_dms_per_day:
            return SendResult(_SKIP, detail="daily reddit-DM cap reached")

        author = _strip_u(target.get("author") or "")
        if not author:
            return SendResult(_FAILED, error_class="config",
                              detail="no target author for reddit_dm")

        if dry_run:
            return SendResult(_SUCCESS, sent=False,
                              detail=f"[dry-run] DM to u/{author}")
        try:
            self._reddit_client().redditor(author).message(
                subject="Quick question", message=draft)
        except Exception as e:  # noqa: BLE001
            return SendResult(_FAILED, sent=True,
                              error_class=_classify_error(str(e)), detail=str(e))
        self._reddit_dms_sent += 1
        time.sleep(uniform(60, 180))
        return SendResult(_SUCCESS, sent=True, detail=f"DM sent to u/{author}")

"""Configuration — read entirely from environment variables (optionally a .env).

The daemon needs three things:
  1. Your SignalPipe operator key   -> SIGNALPIPE_KEY
  2. The brain URL                   -> SIGNALPIPE_API_URL (defaults to prod)
  3. Your platform send credentials  -> Reddit and/or X env vars below

Your platform credentials stay on this machine. They are used only to talk to
Reddit / X directly and are NEVER sent to SignalPipe.

Precedence: an explicit CLI flag > a real environment variable > a .env entry >
the built-in default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_URL = "https://api.signalpipe.io"


def _load_dotenv(path: str = ".env") -> None:
    """Minimal KEY=VALUE .env loader so we don't take a dependency on python-dotenv.

    Uses os.environ.setdefault, so a real environment variable always wins over
    a .env entry.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), val)
    except OSError:
        pass


def _first(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    api_url: str
    key: str
    # Reddit — a "script" app's creds on the SENDING account. Enables
    # reddit_comment (public first-touch) and reddit_dm.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_username: str = ""
    reddit_password: str = ""
    reddit_user_agent: str = "signalpipe-daemon/1.0"
    # X / Twitter — enables twitter_reply.
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""
    # Daily send caps, per channel. Reset at local midnight. Anti-spam pacing.
    max_twitter_per_day: int = 10
    max_reddit_dms_per_day: int = 5
    max_reddit_comments_per_day: int = 15

    @property
    def reddit_ready(self) -> bool:
        return bool(
            self.reddit_client_id and self.reddit_client_secret
            and self.reddit_username and self.reddit_password
        )

    @property
    def twitter_ready(self) -> bool:
        return bool(
            self.x_api_key and self.x_api_secret
            and self.x_access_token and self.x_access_secret
        )


def load_config(api_url: str | None = None, key: str | None = None,
                dotenv: bool = True) -> Config:
    """Build a Config from CLI overrides + environment + optional .env file."""
    if dotenv:
        _load_dotenv()
    return Config(
        api_url=(api_url or _first("SIGNALPIPE_API_URL", "MANTIDAE_API_URL",
                                    default=DEFAULT_API_URL)).rstrip("/"),
        key=key or _first("SIGNALPIPE_KEY", "SIGNALPIPE_OPERATOR_KEY", "MANTIDAE_KEY"),
        reddit_client_id=_first("REDDIT_CLIENT_ID"),
        reddit_client_secret=_first("REDDIT_CLIENT_SECRET"),
        reddit_username=_first("REDDIT_USERNAME"),
        reddit_password=_first("REDDIT_PASSWORD"),
        reddit_user_agent=_first("REDDIT_USER_AGENT", default="signalpipe-daemon/1.0"),
        x_api_key=_first("X_API_KEY"),
        x_api_secret=_first("X_API_SECRET"),
        x_access_token=_first("X_ACCESS_TOKEN"),
        x_access_secret=_first("X_ACCESS_SECRET"),
        max_twitter_per_day=_int_env("MAX_TWITTER_ACTIONS_PER_DAY", 10),
        max_reddit_dms_per_day=_int_env("MAX_REDDIT_DMS_PER_DAY", 5),
        max_reddit_comments_per_day=_int_env("MAX_REDDIT_COMMENTS_PER_DAY", 15),
    )

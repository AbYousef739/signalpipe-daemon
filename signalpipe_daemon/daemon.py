"""The daemon loop: hold the mission stream open, send, ack, reconnect.

This is the orchestrator. It owns no platform knowledge (senders.py) and no wire
format (client.py / sse.py) — it wires them together with a reconnect-with-
backoff policy and at-least-once delivery handling.

Delivery model: the brain streams every 'approved' mission and only stops once
it receives an ack. Within one process a `seen` set guarantees each mission is
posted at most once, even across reconnects. A lost ack therefore never causes a
double-send (the cardinal outreach sin) — at worst it leaves the brain's copy
'approved' for later reconciliation. Exactly-once across process *restarts* needs
brain-side idempotency and is tracked separately.
"""
from __future__ import annotations

import time
from typing import Set

from .client import AuthError, SignalPipeClient
from .config import Config
from .senders import Senders

_BACKOFF_START = 1.0
_BACKOFF_MAX = 60.0
_ACK_RETRIES = 3


def _log(msg: str) -> None:
    print(f"[signalpipe] {msg}", flush=True)


def _version() -> str:
    from . import __version__
    return __version__


def run(config: Config, dry_run: bool = False) -> int:
    """Run the sender until interrupted. Returns a process exit code."""
    client = SignalPipeClient(config.api_url, config.key)
    senders = Senders(config)

    # Preflight: validate the key and surface account state before streaming.
    try:
        status = client.status()
    except AuthError:
        _log("operator key rejected (401). Check SIGNALPIPE_KEY.")
        return 2
    except Exception as e:  # noqa: BLE001 — network/DNS/timeout at startup
        _log(f"cannot reach brain at {config.api_url}: {e}")
        return 1

    _summary(config, status, dry_run)

    seen: Set[str] = set()         # mission ids fully handled this process
    skip_logged: Set[str] = set()  # skip reasons already printed once
    backoff = _BACKOFF_START

    try:
        while True:
            try:
                for event, data in client.stream_missions():
                    if event == "connected":
                        backoff = _BACKOFF_START  # healthy: fast reconnects
                        _log(f"connected — auto-fire threshold "
                             f"{data.get('auto_threshold')}")
                    elif event == "mission_ready":
                        _handle(client, senders,
                                data.get("payload") or data,
                                seen, skip_logged, dry_run)
                    elif event == "heartbeat":
                        if data.get("paused"):
                            _log(f"stream paused (backoff until "
                                 f"{data.get('backoff_until')})")
                    elif event == "shutdown":
                        reason = data.get("reason")
                        if reason == "unauthorized":
                            _log("brain closed stream: unauthorized — exiting.")
                            return 2
                        _log(f"brain closed stream ({reason}); reconnecting.")
                        break
                # generator exhausted: stream closed cleanly → reconnect below
            except AuthError:
                _log("operator key rejected mid-stream (401) — exiting.")
                return 2
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 — any network drop: reconnect
                _log(f"stream error: {e}; reconnecting in {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
    except KeyboardInterrupt:
        _log("shutting down (Ctrl-C).")
        return 0


def _handle(client, senders, mission, seen, skip_logged, dry_run) -> None:
    mid = mission.get("id")
    if not mid:
        _log("mission_ready with no id — ignoring.")
        return
    if mid in seen:
        return  # already handled in this process (at-least-once stream)

    channel = mission.get("outreach_channel") or "manual"
    result = senders.send(mission, dry_run=dry_run)

    # Skip: nothing was sent. Don't ack, don't mark seen — the mission stays
    # 'approved' on the brain and we retry it on a future reconnect (e.g. once a
    # daily cap resets, or once the operator sends a 'manual' one themselves).
    if result.is_skip:
        if mid not in skip_logged:
            _log(f"skip {mid} [{channel}]: {result.detail}")
            skip_logged.add(mid)
        return

    if dry_run:
        _log(f"would-send {mid} [{channel}]: {result.detail}")
        seen.add(mid)
        return

    # Past this point the mission is processed exactly once in this process,
    # regardless of whether the ack lands — so we can never double-send.
    seen.add(mid)

    if result.outcome == "success":
        _log(f"sent {mid} [{channel}]: {result.detail}")
        _ack(client, mid, "success", platform_response=result.detail)
    else:
        _log(f"failed {mid} [{channel}] ({result.error_class}): {result.detail}")
        _ack(client, mid, "failed", error_class=result.error_class,
             platform_response=result.detail)


def _ack(client, mid, outcome, error_class=None, platform_response=None) -> None:
    """Best-effort ack with a short retry. The mission is already in `seen`, so a
    lost ack never re-triggers a send; at worst the brain's copy stays 'approved'
    for later reconciliation."""
    for attempt in range(_ACK_RETRIES):
        try:
            client.ack(mid, outcome, error_class=error_class,
                       platform_response=platform_response)
            return
        except AuthError:
            raise  # fatal — bubble to run()
        except Exception as e:  # noqa: BLE001
            if attempt == _ACK_RETRIES - 1:
                _log(f"ack({outcome}) for {mid} failed after retries: {e}")
                return
            time.sleep(2)


def _summary(config: Config, status: dict, dry_run: bool) -> None:
    _log(f"SignalPipe daemon v{_version()} — the sending runs on you.")
    _log(f"brain:    {config.api_url}")
    _log(f"account:  status={status.get('status', '?')} "
         f"pending={status.get('missions_pending', '?')} "
         f"auto_threshold={status.get('auto_threshold', '?')}")

    channels = []
    if config.twitter_ready:
        channels.append("twitter_reply")
    if config.reddit_ready:
        channels.append("reddit_comment")
        channels.append("reddit_dm")
    _log(f"channels: {', '.join(channels) if channels else 'NONE configured'}")
    _log(f"caps/day: twitter={config.max_twitter_per_day} "
         f"reddit_dm={config.max_reddit_dms_per_day} "
         f"reddit_comment={config.max_reddit_comments_per_day}")
    if dry_run:
        _log("MODE: dry-run — will NOT send or ack; logs intended actions only.")
    if not channels:
        _log("WARNING: no platform credentials set — every mission will fail. "
             "Configure REDDIT_* and/or X_* env vars.")

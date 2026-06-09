"""Command-line entry point: `signalpipe-daemon run` / `status`."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import __version__
from .client import AuthError, SignalPipeClient
from .config import load_config
from .daemon import run


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="signalpipe-daemon",
        description="Send SignalPipe missions with your own platform "
                    "credentials. The math runs on SignalPipe; the sending "
                    "runs on you.",
    )
    p.add_argument("--version", action="version",
                   version=f"signalpipe-daemon {__version__}")
    p.add_argument("--api-url", default=None,
                   help="Brain URL (default: $SIGNALPIPE_API_URL or "
                        "https://api.signalpipe.io)")
    p.add_argument("--key", default=None,
                   help="Operator key (default: $SIGNALPIPE_KEY)")

    sub = p.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Stream missions and send them.")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Log intended sends without posting or acking.")

    sub.add_parser("status", help="Print account/queue status and exit.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = load_config(api_url=args.api_url, key=args.key)
    if not config.key:
        print("error: no operator key. Set SIGNALPIPE_KEY or pass --key.",
              file=sys.stderr)
        return 2

    command = args.command or "run"

    if command == "status":
        client = SignalPipeClient(config.api_url, config.key)
        try:
            print(json.dumps(client.status(), indent=2))
            return 0
        except AuthError:
            print("operator key rejected (401).", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 1

    if command == "run":
        return run(config, dry_run=getattr(args, "dry_run", False))

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

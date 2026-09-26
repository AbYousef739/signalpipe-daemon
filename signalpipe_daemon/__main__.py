"""`python -m signalpipe_daemon` runs the same CLI as the `signalpipe-daemon` command.

Useful on Windows, where the Python installer often leaves its Scripts folder off
PATH: `py -m signalpipe_daemon read` works either way.
"""
import sys

from .cli import main

sys.exit(main())

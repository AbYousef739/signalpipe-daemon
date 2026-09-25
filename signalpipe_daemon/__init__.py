"""SignalPipe Daemon — the user-side sender for SignalPipe v4.

The math runs on SignalPipe. The sending runs on you.

This daemon holds a Server-Sent-Events stream open to your SignalPipe brain,
receives missions the brain has already scored, drafted, and approved, posts
them with YOUR own platform credentials, and acknowledges the result. It never
sees your LLM keys, never scores or drafts anything itself, and keeps no copy
of your pipeline on this machine. It only sends.
"""

__version__ = "1.0.2"

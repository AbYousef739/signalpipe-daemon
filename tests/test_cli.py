"""CLI start-up: HTTPS certificates are checked against the computer's own store when
truststore is installed, and `python -m signalpipe_daemon` runs the CLI."""
import subprocess
import sys
import types
from pathlib import Path

import signalpipe_daemon.cli as cli

ROOT = Path(__file__).resolve().parent.parent


def test_the_system_store_is_used_when_truststore_is_installed(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "truststore",
                        types.SimpleNamespace(inject_into_ssl=lambda: calls.append(1)))
    cli._use_system_certificates()
    assert calls == [1]


def test_a_missing_truststore_is_not_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "truststore", None)  # the import raises ImportError
    cli._use_system_certificates()


def test_main_switches_before_any_request(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_use_system_certificates", lambda: seen.append("certs"))
    monkeypatch.setattr(cli, "load_config",
                        lambda **_k: types.SimpleNamespace(key="", api_url="https://x"))
    assert cli.main(["status"]) == 2  # no key: exits before any request is made
    assert seen == ["certs"]


def test_python_dash_m_runs_the_cli():
    out = subprocess.run([sys.executable, "-m", "signalpipe_daemon", "--version"],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    from signalpipe_daemon import __version__
    assert f"signalpipe-daemon {__version__}" in out.stdout

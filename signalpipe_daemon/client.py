"""HTTP transport to the SignalPipe brain: SSE mission stream + ack + status."""
from __future__ import annotations

from typing import Iterator, Tuple

import requests

from .sse import parse_sse

_CONNECT_TIMEOUT = 10
# Read timeout must exceed the server heartbeat (~30s) so a quiet-but-alive
# stream is not torn down between frames.
_READ_TIMEOUT = 90


class AuthError(Exception):
    """The operator key was rejected (401) — fatal, do not retry."""


class SignalPipeClient:
    def __init__(self, api_url: str, key: str):
        self.api_url = api_url.rstrip("/")
        self.key = key

    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    def status(self) -> dict:
        """GET /v4/sender/status — validates the key and returns queue depth."""
        r = requests.get(f"{self.api_url}/v4/sender/status",
                         headers=self._auth_header(), timeout=20)
        if r.status_code == 401:
            raise AuthError("operator key rejected (401)")
        r.raise_for_status()
        return r.json()

    def list_stations(self) -> list:
        """GET /stations/list — your stations, each with read_by (server|client)."""
        r = requests.get(f"{self.api_url}/stations/list",
                         headers=self._auth_header(), timeout=30)
        if r.status_code == 401:
            raise AuthError("operator key rejected (401)")
        r.raise_for_status()
        return r.json().get("stations", [])

    def ingest(self, station_id: str, entries: list) -> dict:
        """POST /scout/ingest — hand a feed page read on this machine to the brain."""
        r = requests.post(f"{self.api_url}/scout/ingest",
                          json={"station_id": station_id, "entries": entries},
                          headers=self._auth_header(), timeout=30)
        if r.status_code == 401:
            raise AuthError("operator key rejected (401)")
        r.raise_for_status()
        return r.json()

    def preview_station(self, product_id: str, *, entries: list | None = None,
                        rss_url: str | None = None, sample: int | None = None) -> dict:
        """POST /stations/preview — judge a candidate feed before adding it. Saves nothing.

        Send the entries read on this machine, or the URL for the brain to fetch.
        The panel judges up to 12 posts in turn, so this can take a few minutes.
        """
        body: dict = {"product_id": product_id}
        if entries:
            body["entries"] = entries
        else:
            body["rss_url"] = rss_url
        if sample:
            body["sample"] = sample
        r = requests.post(f"{self.api_url}/stations/preview", json=body,
                          headers=self._auth_header(), timeout=300)
        if r.status_code == 401:
            raise AuthError("operator key rejected (401)")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:300]
            raise RuntimeError(f"preview refused ({r.status_code}): {detail}")
        return r.json()

    def ack(self, mission_id: str, outcome: str,
            error_class: str | None = None,
            platform_response: str | None = None) -> None:
        """POST /v4/missions/{id}/ack — report the send result.

        outcome is "success" or "failed". On failure, error_class in
        {"banned","rate_limited",...} lets the brain pause this tenant's stream.
        """
        body: dict = {"outcome": outcome}
        if error_class:
            body["error_class"] = error_class
        if platform_response:
            body["platform_response"] = platform_response[:500]
        r = requests.post(f"{self.api_url}/v4/missions/{mission_id}/ack",
                          json=body, headers=self._auth_header(), timeout=20)
        if r.status_code == 401:
            raise AuthError("operator key rejected (401)")
        r.raise_for_status()

    def stream_missions(self) -> Iterator[Tuple[str, dict]]:
        """Hold GET /v4/missions/stream open, yielding (event_name, data) frames.

        Raises AuthError on 401; lets requests exceptions propagate on a network
        drop so the caller can reconnect with backoff.
        """
        headers = self._auth_header()
        headers["Accept"] = "text/event-stream"
        resp = requests.get(f"{self.api_url}/v4/missions/stream",
                            headers=headers, stream=True,
                            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
        if resp.status_code == 401:
            raise AuthError("operator key rejected (401)")
        resp.raise_for_status()
        yield from parse_sse(resp.iter_lines(decode_unicode=True))

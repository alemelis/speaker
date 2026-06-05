"""Single OwnTone HTTP client for every FOMO service.

Replaces the four ad-hoc `requests.get/put/post` call sites (daemon, tags UI,
metadata rescan, one-off scripts). A shared keep-alive Session removes the
per-call TCP/TLS setup cost (a major source of search slowness), every call has
a timeout (the daemon previously could hang forever), and connection errors get
a small bounded retry. Library search results are cached with a short TTL.
"""

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from .cache import TTLCache


class OwnToneClient:
    def __init__(self, base: str | None = None, timeout: float = 5.0,
                search_ttl: float = 30.0):
        # base includes the /api suffix, e.g. http://host:3689/api
        self.base = (base or config.OWNTONE_API).rstrip("/")
        # host root without /api, used to build absolute artwork URLs
        self.root = self.base[:-4] if self.base.endswith("/api") else self.base
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=2, connect=2, read=1, backoff_factor=0.3,
            status_forcelist=(502, 503, 504), allowed_methods=None,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._search_cache = TTLCache(search_ttl)

    # ---------------- playback (daemon) ----------------

    def enqueue_expression(self, expression: str) -> str | None:
        """Add items matching an OwnTone smart-playlist expression; return first id."""
        r = self.session.post(
            f"{self.base}/queue/items/add",
            params={"expression": expression},
            timeout=self.timeout,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return items[0].get("id")
        return None

    def play(self, item_id: str) -> None:
        self.session.put(
            f"{self.base}/player/play",
            params={"item_id": item_id},
            timeout=self.timeout,
        ).raise_for_status()

    def stop(self) -> None:
        self.session.put(f"{self.base}/player/stop", timeout=self.timeout).raise_for_status()

    def clear_queue(self) -> None:
        self.session.put(f"{self.base}/queue/clear", timeout=self.timeout).raise_for_status()

    # ---------------- search (UIs) ----------------

    def search(self, owntone_type: str, query: str, limit: int = 20) -> dict:
        """Raw OwnTone search. owntone_type is 'tracks' or 'albums'. Cached by TTL."""
        key = (owntone_type, query, limit)
        cached = self._search_cache.get(key)
        if cached is not None:
            return cached
        r = self.session.get(
            f"{self.base}/search",
            params={"type": owntone_type, "query": query, "limit": limit},
            timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        self._search_cache.set(key, payload)
        return payload

    # ---------------- library maintenance ----------------

    def rescan(self) -> dict[str, Any]:
        """Trigger a library rescan; tolerates /update vs /rescan naming."""
        errors: list[str] = []
        for path in ("/update", "/rescan"):
            try:
                resp = self.session.put(f"{self.base}{path}", timeout=10)
                resp.raise_for_status()
                self._search_cache.clear()
                return {"ok": True, "endpoint": f"{self.base}{path}",
                        "message": "Owntone rescan triggered."}
            except requests.RequestException as exc:
                errors.append(f"{self.base}{path}: {exc}")
        return {"ok": False, "endpoint": f"{self.base}/update",
                "message": " | ".join(errors)}

    # ---------------- artwork ----------------

    def artwork_url(self, relative: str) -> str:
        """Turn an OwnTone artwork_url (e.g. '/artwork/item/123') into an absolute URL."""
        if relative.startswith("http"):
            return relative
        return f"{self.root}{relative}"

    def fetch_artwork(self, relative: str) -> requests.Response:
        """Stream artwork bytes from OwnTone for the /artwork proxy."""
        return self.session.get(self.artwork_url(relative), timeout=self.timeout, stream=True)

    # ---------------- browse (library catalog) ----------------

    def list_albums(self, limit: int = 500, offset: int = 0) -> dict:
        r = self.session.get(
            f"{self.base}/library/albums",
            params={"limit": limit, "offset": offset},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def album_tracks(self, album_id: str, limit: int = 200) -> dict:
        r = self.session.get(
            f"{self.base}/library/albums/{album_id}/tracks",
            params={"limit": limit},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

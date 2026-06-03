from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core import config
from core.web_utils import SPAStaticFiles

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"

_LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
_album_cache: dict[str, str] = {}


def _params(method: str, **kwargs) -> dict:
    return {"method": method, "api_key": config.LASTFM_API_KEY, "format": "json", **kwargs}


def _fetch_album(artist: str, track: str) -> str:
    key = f"{artist}\t{track}"
    if key in _album_cache:
        return _album_cache[key]
    try:
        r = requests.get(
            _LASTFM_BASE,
            params=_params("track.getInfo", artist=artist, track=track, autocorrect=1),
            timeout=4,
        )
        r.raise_for_status()
        album = r.json().get("track", {}).get("album", {}).get("title", "")
        _album_cache[key] = album
        return album
    except Exception:  # noqa: BLE001
        return ""


class SimilarRequest(BaseModel):
    query: str  # "Artist - Track"


@app.post("/api/similar")
def find_similar(body: SimilarRequest):
    if not config.LASTFM_API_KEY:
        raise HTTPException(503, detail="LASTFM_API_KEY is not set.")

    q = body.query.strip()
    if " - " not in q:
        raise HTTPException(422, detail='Use "Artist - Track" format, e.g. "Fu Manchu - Eatin Dust".')
    artist, track = q.split(" - ", 1)

    try:
        res = requests.get(
            _LASTFM_BASE,
            params=_params(
                "track.getSimilar",
                artist=artist.strip(),
                track=track.strip(),
                autocorrect=1,
                limit=20,
            ),
            timeout=10,
        )
        res.raise_for_status()
    except requests.HTTPError as exc:
        raise HTTPException(502, detail=f"Last.fm: {exc}") from exc
    except requests.RequestException as exc:
        raise HTTPException(502, detail=str(exc)) from exc

    data = res.json()
    if "error" in data:
        return {"results": [], "message": data.get("message", "Track not found.")}

    raw = data.get("similartracks", {}).get("track", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not raw:
        return {"results": [], "message": "No similar tracks found."}

    tracks = [{"artist": t.get("artist", {}).get("name", ""), "title": t.get("name", "")} for t in raw]

    def enrich(t):
        t["album"] = _fetch_album(t["artist"], t["title"])
        return t

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(enrich, tracks))

    return {"results": results}


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

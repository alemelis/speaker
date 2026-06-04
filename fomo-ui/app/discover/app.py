from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core import config
from core.web_utils import SPAStaticFiles

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Last.fm helpers
# ---------------------------------------------------------------------------
_LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
_album_cache: dict[str, str] = {}


def _lastfm_get(method: str, **kwargs) -> dict:
    r = requests.get(
        _LASTFM_BASE,
        params={"method": method, "api_key": config.LASTFM_API_KEY, "format": "json", **kwargs},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _fetch_album(artist: str, track: str) -> str:
    key = f"{artist}\t{track}"
    if key in _album_cache:
        return _album_cache[key]
    try:
        data = _lastfm_get("track.getInfo", artist=artist, track=track, autocorrect=1)
        album = data.get("track", {}).get("album", {}).get("title", "")
    except Exception:  # noqa: BLE001
        album = ""
    _album_cache[key] = album
    return album


def _enrich_albums(tracks: list[dict]) -> list[dict]:
    def one(t: dict) -> dict:
        t["album"] = _fetch_album(t["artist"], t["title"])
        return t
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, tracks))


# ---------------------------------------------------------------------------
# MusicBrainz helpers (no key needed, just User-Agent)
# ---------------------------------------------------------------------------
_MB_BASE = "https://musicbrainz.org/ws/2"
_MB_HEADERS = {"User-Agent": "FOMO-jukebox/1.0 (https://github.com/alemelis/speaker)"}


def _mb_get(path: str, **params) -> dict:
    params["fmt"] = "json"
    r = requests.get(f"{_MB_BASE}/{path}", params=params, headers=_MB_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class DiscoverRequest(BaseModel):
    mode: Literal["similar_tracks", "similar_artists", "song", "discography"]
    query: str


# ---------------------------------------------------------------------------
# Mode handlers
#   result_type "tracks"  -> [{artist, title, album}]
#   result_type "artists" -> [{artist}]
#   result_type "albums"  -> [{artist, album, year}]
# ---------------------------------------------------------------------------

def _similar_tracks(q: str) -> dict:
    if " - " not in q:
        raise HTTPException(422, detail='Use "Artist - Track" format, e.g. "Fu Manchu - Eatin Dust".')
    artist, track = (s.strip() for s in q.split(" - ", 1))
    data = _lastfm_get("track.getSimilar", artist=artist, track=track, autocorrect=1, limit=20)
    if "error" in data:
        return {"results": [], "result_type": "tracks", "message": data.get("message", "Track not found.")}
    raw = data.get("similartracks", {}).get("track", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not raw:
        return {"results": [], "result_type": "tracks", "message": "No similar tracks found."}
    tracks = [{"artist": t.get("artist", {}).get("name", ""), "title": t.get("name", "")} for t in raw]
    return {"results": _enrich_albums(tracks), "result_type": "tracks"}


def _similar_artists(q: str) -> dict:
    data = _lastfm_get("artist.getSimilar", artist=q, autocorrect=1, limit=24)
    if "error" in data:
        return {"results": [], "result_type": "artists", "message": data.get("message", "Artist not found.")}
    raw = data.get("similarartists", {}).get("artist", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not raw:
        return {"results": [], "result_type": "artists", "message": "No similar artists found."}
    return {"results": [{"artist": a.get("name", "")} for a in raw], "result_type": "artists"}


def _song_lookup(q: str) -> dict:
    data = _lastfm_get("track.search", track=q, limit=12)
    if "error" in data:
        return {"results": [], "result_type": "tracks", "message": data.get("message", "Search failed.")}
    raw = data.get("results", {}).get("trackmatches", {}).get("track", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not raw:
        return {"results": [], "result_type": "tracks", "message": "No songs found."}
    tracks = [{"artist": t.get("artist", ""), "title": t.get("name", "")} for t in raw]
    return {"results": _enrich_albums(tracks), "result_type": "tracks"}


def _discography(q: str) -> dict:
    try:
        found = _mb_get("artist", query=q, limit=1).get("artists", [])
        if not found:
            return {"results": [], "result_type": "albums", "message": "Artist not found."}
        artist_name, mbid = found[0]["name"], found[0]["id"]
        groups = _mb_get("release-group", artist=mbid, type="album", limit=100).get("release-groups", [])
    except requests.RequestException as exc:
        raise HTTPException(502, detail=f"MusicBrainz: {exc}") from exc

    albums = []
    for g in groups:
        if g.get("primary-type") != "Album" or g.get("secondary-types"):
            continue
        year = (g.get("first-release-date") or "")[:4]
        albums.append({"artist": artist_name, "album": g.get("title", ""), "year": year, "mbid": g.get("id", "")})
    albums.sort(key=lambda a: a["year"] or "9999")
    if not albums:
        return {"results": [], "result_type": "albums", "message": "No studio albums found."}
    return {"results": albums, "result_type": "albums"}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@app.post("/api/discover")
def discover(body: DiscoverRequest):
    q = body.query.strip()
    if not q:
        raise HTTPException(422, detail="Empty query.")
    if body.mode != "discography" and not config.LASTFM_API_KEY:
        raise HTTPException(503, detail="LASTFM_API_KEY is not set.")
    try:
        if body.mode == "similar_tracks":
            return _similar_tracks(q)
        if body.mode == "similar_artists":
            return _similar_artists(q)
        if body.mode == "song":
            return _song_lookup(q)
        return _discography(q)
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(502, detail=str(exc)) from exc


@app.get("/api/tracks")
def get_tracks(artist: str, album: str):
    if not config.LASTFM_API_KEY:
        raise HTTPException(503, detail="LASTFM_API_KEY is not set.")
    try:
        data = _lastfm_get("album.getInfo", artist=artist, album=album, autocorrect=1)
    except requests.RequestException as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    if "error" in data:
        return {"tracks": []}
    raw = data.get("album", {}).get("tracks", {}).get("track", [])
    if isinstance(raw, dict):
        raw = [raw]
    tracks = [
        {"title": t.get("name", ""), "duration": int(t.get("duration") or 0)}
        for t in raw
    ]
    return {"tracks": tracks}


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

from pathlib import Path

from fastapi import FastAPI, HTTPException

from core.owntone import OwnToneClient
from core.web_utils import SPAStaticFiles

app = FastAPI(title="FOMO Browse")
_client = OwnToneClient()
STATIC_DIR = Path(__file__).parent / "static"


def _norm_art(raw: str) -> str:
    """OwnTone returns './artwork/...' — make it '/artwork/...' for the proxy."""
    if raw and raw.startswith("./"):
        return raw[1:]
    return raw or ""


@app.get("/api/albums")
def get_albums():
    try:
        data = _client.list_albums()
    except Exception as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    albums = [
        {
            "id": item["id"],
            "album": item.get("name", ""),
            "artist": item.get("artist", ""),
            "year": str(item.get("year", "") or "")[:4],
            "track_count": item.get("track_count", 0),
            "art": _norm_art(item.get("artwork_url", "")),
        }
        for item in data.get("items", [])
    ]
    albums.sort(key=lambda a: (a["artist"].lower(), a["album"].lower()))
    return {"albums": albums, "total": data.get("total", len(albums))}


@app.get("/api/album/{album_id}/tracks")
def get_album_tracks(album_id: str):
    try:
        data = _client.album_tracks(album_id)
    except Exception as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    tracks = sorted(
        [
            {
                "track_number": item.get("track_number", 0),
                "title": item.get("title", ""),
                "length_ms": item.get("length_ms", 0),
            }
            for item in data.get("items", [])
        ],
        key=lambda t: t["track_number"],
    )
    return {"tracks": tracks}


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

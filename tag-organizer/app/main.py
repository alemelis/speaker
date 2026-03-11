import os
import re
import socket
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

sys.path.insert(0, "/app")
import db

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


class TagMapping(BaseModel):
    tag_id: str
    query_raw: str
    kind: str
    query_text: str


class SearchResult(BaseModel):
    label: str
    query_text: str
    kind: str
    uri: str | None = None


class UpsertTagRequest(BaseModel):
    tag_id: str
    kind: str
    query_text: str


FOMO_DB = os.getenv("FOMO_DB", "/data/fomo.db")
OWNTONE_API = os.getenv("OWNTONE_API", "").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DOCKER_SOCKET = "/var/run/docker.sock"
RFID_CONTAINER = os.getenv("RFID_CONTAINER", "rfid-daemon")
_UNKNOWN_TAG_RE = re.compile(r"Unknown tag:\s*(\d+)")

TRACK_PREFIX = "tracks&query="
ALBUM_PREFIX = "albums&query="

app = FastAPI(title="RFID Tag Organizer")
api_router = APIRouter(prefix="/api")

_local = threading.local()


def get_conn():
    if not hasattr(_local, "conn"):
        _local.conn = db.connect(FOMO_DB)
    return _local.conn


def _build_query(kind: str, query_text: str) -> str:
    normalized_kind = kind.strip().lower()
    encoded = quote_plus(query_text.strip())
    if normalized_kind == "track":
        return f"{TRACK_PREFIX}{encoded}"
    if normalized_kind == "album":
        return f"{ALBUM_PREFIX}{encoded}"
    raise HTTPException(status_code=400, detail="kind must be 'track' or 'album'.")


@api_router.get("/tags")
def list_tags() -> list[TagMapping]:
    rows = db.all_tags(get_conn())
    return [
        TagMapping(
            tag_id=row["tag_id"],
            query_raw=_build_query(row["kind"], row["query"]),
            kind=row["kind"],
            query_text=row["query"],
        )
        for row in rows
    ]


@api_router.get("/search")
def search_owntone(kind: str, q: str, limit: int = 20) -> list[SearchResult]:
    if not OWNTONE_API:
        raise HTTPException(status_code=500, detail="OWNTONE_API is not configured.")

    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"track", "album"}:
        raise HTTPException(status_code=400, detail="kind must be 'track' or 'album'.")

    if not q.strip():
        return []

    owntone_type = "tracks" if normalized_kind == "track" else "albums"
    endpoint = f"{OWNTONE_API}/search"

    try:
        resp = requests.get(
            endpoint,
            params={"type": owntone_type, "query": q.strip(), "limit": max(1, min(limit, 50))},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Owntone search failed: {exc}") from exc

    items = payload.get(owntone_type, {}).get("items", [])
    results: list[SearchResult] = []
    for item in items:
        if normalized_kind == "track":
            title = item.get("title") or ""
            artist = item.get("artist") or ""
            label = f"{title} — {artist}" if artist else title
            query_text = title
        else:
            album_name = item.get("name") or ""
            artist = item.get("artist") or ""
            label = f"{album_name} — {artist}" if artist else album_name
            query_text = album_name

        results.append(
            SearchResult(
                label=label.strip() or "(untitled)",
                query_text=query_text.strip(),
                kind=normalized_kind,
                uri=item.get("uri"),
            )
        )
    return results


@api_router.post("/tags")
def upsert_tag(payload: UpsertTagRequest) -> dict[str, Any]:
    tag_id = payload.tag_id.strip()
    if not tag_id:
        raise HTTPException(status_code=400, detail="tag_id is required.")

    query_text = payload.query_text.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required.")

    kind = payload.kind.strip().lower()
    if kind not in {"track", "album"}:
        raise HTTPException(status_code=400, detail="kind must be 'track' or 'album'.")

    db.upsert_tag(get_conn(), tag_id, kind, query_text)
    return {"ok": True, "tag_id": tag_id, "query_raw": _build_query(kind, query_text)}


@api_router.delete("/tags/{tag_id}")
def delete_tag(tag_id: str) -> dict[str, Any]:
    found = db.delete_tag(get_conn(), tag_id)
    if not found:
        raise HTTPException(status_code=404, detail="Tag ID not found.")
    return {"ok": True, "tag_id": tag_id}


def _docker_logs(container: str, tail: int = 200) -> str:
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail="Docker socket not available.")
    request = (
        f"GET /containers/{container}/logs?stdout=1&stderr=1&tail={tail} HTTP/1.0\r\n"
        f"Host: localhost\r\n\r\n"
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(DOCKER_SOCKET)
        sock.sendall(request.encode())
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    _, _, body = raw.partition(b"\r\n\r\n")
    text_parts: list[str] = []
    pos = 0
    while pos + 8 <= len(body):
        frame_size = int.from_bytes(body[pos + 4 : pos + 8], "big")
        pos += 8
        text_parts.append(body[pos : pos + frame_size].decode("utf-8", errors="replace"))
        pos += frame_size
    return "".join(text_parts)


@api_router.get("/unknown-tags")
def unknown_tags(tail: int = 200) -> list[str]:
    try:
        log_text = _docker_logs(RFID_CONTAINER, tail)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read logs: {exc}") from exc

    found = _UNKNOWN_TAG_RE.findall(log_text)
    if not found:
        return []

    known = {row["tag_id"] for row in db.all_tags(get_conn())}

    seen: list[str] = []
    seen_set: set[str] = set()
    for tag_id in reversed(found):
        if tag_id not in known and tag_id not in seen_set:
            seen.append(tag_id)
            seen_set.add(tag_id)
    return seen


@api_router.get("/plays")
def get_plays(limit: int = 50) -> list[dict]:
    return db.recent_plays(get_conn(), limit)


@api_router.get("/plays/top")
def get_top_plays(limit: int = 20) -> list[dict]:
    return db.play_counts(get_conn(), limit)


app.include_router(api_router)
app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

import os
import re
import socket
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote_plus, unquote_plus

import requests
import yaml
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


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


TAGS_FILE = Path(os.getenv("TAGS_FILE", "/data/tags.yaml"))
OWNTONE_API = os.getenv("OWNTONE_API", "").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parent / "static"
DOCKER_SOCKET = "/var/run/docker.sock"
RFID_CONTAINER = os.getenv("RFID_CONTAINER", "rfid-daemon")
# Matches lines like: 2026-03-04T... [WARNING] Unknown tag: 1234567890
_UNKNOWN_TAG_RE = re.compile(r"Unknown tag:\s*(\d+)")

TRACK_PREFIX = "tracks&query="
ALBUM_PREFIX = "albums&query="

app = FastAPI(title="RFID Tag Organizer")
api_router = APIRouter(prefix="/api")


def _read_tags_map() -> dict[int | str, str]:
    if not TAGS_FILE.exists():
        return {}
    with TAGS_FILE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="tags.yaml must contain a mapping.")
    return data


def _coerce_key(tag_id: str) -> int | str:
    try:
        return int(tag_id)
    except ValueError:
        return tag_id


def _save_tags_map(data: dict[int | str, str]) -> None:
    TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", delete=False, dir=str(TAGS_FILE.parent), encoding="utf-8") as tmp:
        yaml.safe_dump(data, tmp, sort_keys=False, allow_unicode=True)
        temp_name = tmp.name
    Path(temp_name).replace(TAGS_FILE)


def _parse_query(raw_query: str) -> tuple[str, str]:
    if raw_query.startswith(TRACK_PREFIX):
        return "track", unquote_plus(raw_query[len(TRACK_PREFIX):])
    if raw_query.startswith(ALBUM_PREFIX):
        return "album", unquote_plus(raw_query[len(ALBUM_PREFIX):])
    return "unknown", raw_query


def _build_query(kind: str, query_text: str) -> str:
    normalized_kind = kind.strip().lower()
    encoded = quote_plus(query_text.strip())
    if normalized_kind == "track":
        return f"{TRACK_PREFIX}{encoded}"
    if normalized_kind == "album":
        return f"{ALBUM_PREFIX}{encoded}"
    raise HTTPException(status_code=400, detail="kind must be 'track' or 'album'.")


def _sort_key(item: tuple[int | str, str]) -> tuple[int, str]:
    key = str(item[0])
    return (0, f"{int(key):020d}") if key.isdigit() else (1, key)


@api_router.get("/tags")
def list_tags() -> list[TagMapping]:
    mappings = _read_tags_map()
    rows: list[TagMapping] = []
    for tag_id, raw_query in sorted(mappings.items(), key=_sort_key):
        raw_text = str(raw_query)
        kind, query_text = _parse_query(raw_text)
        rows.append(
            TagMapping(
                tag_id=str(tag_id),
                query_raw=raw_text,
                kind=kind,
                query_text=query_text,
            )
        )
    return rows


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

    query_raw = _build_query(payload.kind, query_text)
    mappings = _read_tags_map()
    mappings[_coerce_key(tag_id)] = query_raw
    _save_tags_map(mappings)
    return {"ok": True, "tag_id": tag_id, "query_raw": query_raw}


@api_router.delete("/tags/{tag_id}")
def delete_tag(tag_id: str) -> dict[str, Any]:
    mappings = _read_tags_map()
    key = _coerce_key(tag_id)
    if key not in mappings:
        raise HTTPException(status_code=404, detail="Tag ID not found.")
    del mappings[key]
    _save_tags_map(mappings)
    return {"ok": True, "tag_id": tag_id}


def _docker_logs(container: str, tail: int = 200) -> str:
    """Fetch the last *tail* log lines from a container via the Docker socket."""
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
    # Strip HTTP headers (everything before the first blank line)
    _, _, body = raw.partition(b"\r\n\r\n")
    # Docker multiplexed stream: each log frame has an 8-byte header;
    # strip them so we get plain text.
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
    """Return tag IDs seen in rfid-daemon logs that are not yet in tags.yaml."""
    try:
        log_text = _docker_logs(RFID_CONTAINER, tail)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read logs: {exc}") from exc

    found = _UNKNOWN_TAG_RE.findall(log_text)
    if not found:
        return []

    try:
        known = set(str(k) for k in _read_tags_map().keys())
    except Exception:
        known = set()

    seen: list[str] = []
    seen_set: set[str] = set()
    for tag_id in reversed(found):  # most-recent first
        if tag_id not in known and tag_id not in seen_set:
            seen.append(tag_id)
            seen_set.add(tag_id)
    return seen


app.include_router(api_router)
app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.owntone import OwnToneClient
from core.web_utils import SPAStaticFiles

from .indexer import get_index, rebuild, remove_one, update_one
from .metadata import read_tags, validate_path, write_tags


client = OwnToneClient()


class TrackPatchRequest(BaseModel):
    path: str
    tags: dict[str, Any] = Field(default_factory=dict)


class BatchPatchRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)


class ProbeRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class FixFromFilenameRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class FrontendLogRequest(BaseModel):
    level: str = "error"
    message: str
    source: str | None = None
    stack: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


MUSIC_ROOT = Path(os.getenv("MUSIC_ROOT", "/music"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("metadata-webui.frontend")


async def _probe_file(abs_path: Path) -> str | None:
    """Run ffprobe on a file. Returns an error string, or None if clean."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_name,duration",
        "-of", "json", str(abs_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    err = stderr.decode(errors="replace").strip()
    if proc.returncode != 0 or err:
        return err or "ffprobe check failed"
    return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    rebuild(MUSIC_ROOT)
    yield


app = FastAPI(title="Owntone Metadata WebUI", lifespan=lifespan)
api_router = APIRouter(prefix="/api")


@api_router.get("/index")
def get_index_endpoint() -> list[dict[str, Any]]:
    return get_index()


@api_router.get("/track")
def get_track_endpoint(path: str) -> dict[str, Any]:
    abs_path = validate_path(path, MUSIC_ROOT)
    return read_tags(abs_path, MUSIC_ROOT)


@api_router.patch("/track")
def patch_track_endpoint(payload: TrackPatchRequest) -> dict[str, Any]:
    abs_path = validate_path(payload.path, MUSIC_ROOT)
    write_tags(abs_path, payload.tags)
    update_one(payload.path, MUSIC_ROOT)
    return {"ok": True, "path": payload.path}


@api_router.post("/batch")
def patch_batch_endpoint(payload: BatchPatchRequest) -> dict[str, Any]:
    updated = 0
    for path in payload.paths:
        abs_path = validate_path(path, MUSIC_ROOT)
        write_tags(abs_path, payload.tags)
        update_one(path, MUSIC_ROOT)
        updated += 1

    return {"ok": True, "updated": updated}


@api_router.post("/rebuild")
def rebuild_endpoint() -> dict[str, Any]:
    count = rebuild(MUSIC_ROOT)
    return {"ok": True, "count": count}


@api_router.post("/rescan")
def rescan_endpoint() -> dict[str, Any]:
    return client.rescan()


@api_router.post("/fix-from-filename")
def fix_from_filename_endpoint(payload: FixFromFilenameRequest) -> dict[str, Any]:
    updated = 0
    for path in payload.paths:
        abs_path = validate_path(path, MUSIC_ROOT)
        stem = abs_path.stem
        parts = stem.split("-", 1)
        tags: dict[str, Any] = {}
        if len(parts) == 2 and parts[0].isdigit():
            tags["tracknumber"] = str(int(parts[0]))
            tags["title"] = parts[1].strip()
        else:
            tags["title"] = stem
        write_tags(abs_path, tags)
        update_one(path, MUSIC_ROOT)
        updated += 1
    return {"ok": True, "updated": updated}


@api_router.post("/probe")
async def probe_endpoint(payload: ProbeRequest) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for path in payload.paths:
        try:
            abs_path = validate_path(path, MUSIC_ROOT)
            error = await _probe_file(abs_path)
            results[path] = {"ok": error is None, "error": error}
        except HTTPException as exc:
            results[path] = {"ok": False, "error": exc.detail}
    return {"results": results}


@api_router.delete("/track")
def delete_track_endpoint(path: str) -> dict[str, Any]:
    abs_path = validate_path(path, MUSIC_ROOT)
    abs_path.unlink()
    remove_one(path)
    return {"ok": True, "path": path}


@api_router.post("/frontend-log")
def frontend_log_endpoint(payload: FrontendLogRequest) -> dict[str, bool]:
    log_level = payload.level.upper()
    formatted = (
        f"frontend[{payload.source or 'unknown'}] {payload.message}"
        f" context={payload.context} stack={payload.stack}"
    )
    if log_level == "WARN":
        logger.warning(formatted)
    elif log_level == "INFO":
        logger.info(formatted)
    else:
        logger.error(formatted)
    return {"ok": True}


app.include_router(api_router)
app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

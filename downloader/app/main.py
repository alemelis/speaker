import asyncio
import json
import logging
import os
import re as _re
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fomo")

_ansi_re = _re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ansi_re.sub("", s)


async def _probe_file(path: Path) -> str | None:
    """Run ffprobe on path. Returns an error string, or None if clean."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_name,duration",
        "-of", "json", str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    err = stderr.decode(errors="replace").strip()
    if proc.returncode != 0 or err:
        return err or "ffprobe check failed"
    return None


class _Logger:
    """yt-dlp logger that routes item-level errors to a callback."""

    def __init__(self, on_error):
        self._on_error = on_error

    def debug(self, msg: str) -> None: pass
    def info(self, msg: str) -> None: pass
    def warning(self, msg: str) -> None: pass

    def error(self, msg: str) -> None:
        self._on_error(_strip_ansi(msg))


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        response.headers["Cache-Control"] = "no-store"
        return response


class SearchRequest(BaseModel):
    query: str
    max_results: int = 8


class PlaylistInfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    artist: str = ""
    album: str = ""
    title: str = ""
    playlist: bool = False
    delay: int = 0
    selected_items: list[int] = []  # 1-based original playlist indices


SAVE_DIR = Path(os.getenv("SAVE_DIR", "/music"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="FOMO Downloader")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    log.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.post("/api/search")
async def search(req: SearchRequest):
    from youtubesearchpython import VideosSearch, PlaylistsSearch  # noqa: PLC0415

    log.info("search query=%r max_results=%d", req.query, req.max_results)
    half = max(req.max_results // 2, 3)

    def _videos():
        return VideosSearch(req.query, limit=half).result()

    def _playlists():
        return PlaylistsSearch(req.query, limit=half).result()

    try:
        vs, ps = await asyncio.gather(
            asyncio.to_thread(_videos),
            asyncio.to_thread(_playlists),
        )
    except Exception as exc:
        log.exception("search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    videos = [
        {
            "type": "video",
            "url": v["link"],
            "title": v.get("title", ""),
            "channel": (v.get("channel") or {}).get("name", ""),
            "duration": v.get("duration", ""),
            "thumbnail": ((v.get("thumbnails") or [{}])[0]).get("url", ""),
        }
        for v in vs.get("result", [])
    ]
    playlists = [
        {
            "type": "playlist",
            "url": p["link"],
            "title": p.get("title", ""),
            "thumbnail": ((p.get("thumbnails") or [{}])[0]).get("url", ""),
        }
        for p in ps.get("result", [])
    ]
    log.info("search done: %d videos, %d playlists", len(videos), len(playlists))
    return {"videos": videos, "playlists": playlists}


@app.post("/api/playlist-info")
async def playlist_info(req: PlaylistInfoRequest):
    from yt_dlp import YoutubeDL  # noqa: PLC0415

    log.info("playlist-info url=%r", req.url)

    def _fetch():
        opts = {"flat_playlist": True, "quiet": True, "no_warnings": True}
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(req.url, download=False)

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        log.error("playlist-info failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    entries = [
        {"index": i, "title": entry.get("title", f"Track {i}")}
        for i, entry in enumerate(data.get("entries", []), 1)
    ]
    log.info("playlist-info done: %d entries", len(entries))
    return {"entries": entries}


@app.post("/api/download")
async def download(req: DownloadRequest) -> StreamingResponse:
    log.info(
        "download url=%r artist=%r album=%r title=%r playlist=%s delay=%d",
        req.url, req.artist, req.album, req.title, req.playlist, req.delay,
    )
    return StreamingResponse(
        _run_download(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _run_download(req: DownloadRequest) -> AsyncGenerator[str, None]:
    from yt_dlp import YoutubeDL  # noqa: PLC0415
    import yt_dlp.utils  # noqa: PLC0415

    artist = req.artist.strip()
    album = req.album.strip()
    title = req.title.strip()

    if req.playlist:
        dirname = f"{artist}-{album}" if artist and album else (artist or album or "playlist")
        savedir = SAVE_DIR / dirname
        output_template = "%(autonumber)02d-%(title)s"
    else:
        dirname = artist if artist else "unknown"
        savedir = SAVE_DIR / dirname
        output_template = title if title else "%(title)s"

    savedir.mkdir(parents=True, exist_ok=True)
    before_files = set(savedir.glob("*.m4a"))

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    state = {"done": 0, "total": len(req.selected_items) if req.playlist and req.selected_items else 1}

    def on_item_error(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "warn", "msg": msg})

    def progress_hook(d):
        status = d.get("status")
        if status == "finished":
            info = d.get("info_dict") or {}
            playlist_count = info.get("n_entries") or info.get("playlist_count") or state["total"]
            playlist_index = info.get("playlist_index") or 1
            state["total"] = playlist_count
            state["done"] = playlist_index
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "done": state["done"], "total": state["total"]},
            )
        elif status == "error":
            err = _strip_ansi(str(d.get("error", "item failed")))
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "warn", "msg": err})

    pp_args: list[str] = []
    if artist:
        pp_args += ["-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}"]
    if album:
        pp_args += ["-metadata", f"album={album}"]
    if not req.playlist and title:
        pp_args += ["-metadata", f"title={title}"]

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "noplaylist": not req.playlist,
        "outtmpl": output_template,
        "paths": {"home": str(savedir)},
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"},
        ],
        "writethumbnail": True,
        "embedthumbnail": True,
        "addmetadata": True,
        "parse_metadata": [
            "autonumber:%(track_number)s" if req.playlist else "1:%(track_number)s"
        ],
        "ignoreerrors": True,
        "logger": _Logger(on_item_error),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
    }

    if pp_args:
        ydl_opts["postprocessor_args"] = {"Metadata": pp_args}

    if req.playlist and req.selected_items:
        ydl_opts["playlist_items"] = ",".join(str(i) for i in req.selected_items)

    error_holder: list[str] = []

    def run():
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([req.url])
        except yt_dlp.utils.DownloadError as exc:
            error_holder.append(_strip_ansi(str(exc)))
        except Exception as exc:
            error_holder.append(str(exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "_done"})

    task = asyncio.create_task(asyncio.to_thread(run))

    while True:
        event = await queue.get()
        if event["type"] == "_done":
            break
        elif event["type"] == "progress":
            yield _sse("progress", json.dumps({"done": event["done"], "total": event["total"]}))
        elif event["type"] == "warn":
            log.warning("download warn: %s", event["msg"])
            yield _sse("warn", event["msg"])

    await task

    if error_holder:
        log.error("download failed: %s", error_holder[0])
        yield _sse("error", error_holder[0])
        return

    # Ensure bar always reaches 100%
    if state["done"] < state["total"]:
        yield _sse("progress", json.dumps({"done": state["total"], "total": state["total"]}))

    if req.playlist:
        m3u_path = savedir / f"{dirname}.m3u"
        m3u_path.write_text("\n".join(str(f) for f in sorted(savedir.glob("*.m4a"))) + "\n")

    # Probe newly downloaded files for corruption
    new_files = sorted(set(savedir.glob("*.m4a")) - before_files)
    for f in new_files:
        probe_err = await _probe_file(f)
        if probe_err:
            log.warning("probe failed for %s: %s", f.name, probe_err)
            yield _sse("warn", f"{f.name}: {probe_err}")

    if not req.playlist and req.delay:
        m4a_files = sorted(savedir.glob("*.m4a"))
        dst = m4a_files[0] if m4a_files else None
        if dst and dst.exists():
            tmp = Path("/tmp/temp_audio.m4a")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(dst), "-ss", str(req.delay), "-c", "copy", str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await proc.wait() == 0:
                tmp.replace(dst)
            else:
                yield _sse("error", "delay trim failed")
                return

    log.info("download done: savedir=%s", savedir)
    yield _sse("done", "")


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

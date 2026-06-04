import asyncio
import json
import logging
import re as _re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import artwork, config, db
from core.cache import TTLCache
from core.web_utils import SPAStaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fomo")

_ansi_re = _re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ansi_re.sub("", s)


def _fmt_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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
    """yt-dlp logger that routes messages to callbacks."""

    def __init__(self, on_error, on_status):
        self._on_error = on_error
        self._on_status = on_status

    def debug(self, msg: str) -> None:
        msg = _strip_ansi(msg).strip()
        if msg:
            self._on_status(msg)

    def info(self, msg: str) -> None:
        msg = _strip_ansi(msg).strip()
        if msg:
            self._on_status(msg)

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        self._on_error(_strip_ansi(msg))


class SearchRequest(BaseModel):
    query: str
    max_results: int = 20


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


SAVE_DIR = config.SAVE_DIR
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="FOMO Downloader")

# Shared SQLite connection (WAL, check_same_thread=False) for download-job state.
_conn = db.connect(config.FOMO_DB)
_search_cache = TTLCache(300.0)

# Live SSE fan-out: job_id -> set of subscriber queues. Jobs run regardless of
# whether anyone is currently subscribed, so a download survives leaving the page.
_subscribers: dict[str, set[asyncio.Queue]] = {}
_cancelled: set[str] = set()

# Any job left "running"/"queued" by a previous process can't be resumed mid-file.
for _d in db.list_downloads(_conn, 200):
    if _d["status"] in ("running", "queued"):
        db.update_download(_conn, _d["job_id"], status="error", error="interrupted by restart")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    log.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _publish(job_id: str, event: str, data: str) -> None:
    for q in list(_subscribers.get(job_id, ())):
        q.put_nowait({"event": event, "data": data})


def _emit(job_id: str, event: str, data: str) -> None:
    """Persist job state to SQLite and fan the event out to live subscribers."""
    if event == "progress":
        d = json.loads(data)
        db.update_download(_conn, job_id, status="running", done=d["done"], total=d["total"])
    elif event == "status":
        db.update_download(_conn, job_id, status="running", message=data)
    elif event == "done":
        db.update_download(_conn, job_id, status="done", message="")
    elif event == "failed":
        db.update_download(_conn, job_id, status="error", error=data)
    elif event == "cancelled":
        db.update_download(_conn, job_id, status="cancelled", message="cancelled")
    _publish(job_id, event, data)


# ---------------- search ----------------

@app.post("/api/search")
async def search(req: SearchRequest):
    n = max(1, min(req.max_results, 20))
    cache_key = (req.query.strip(), n)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    log.info("search query=%r max_results=%d", req.query, n)
    half = max(n // 2, 3)

    try:
        videos, playlists = await asyncio.gather(
            asyncio.to_thread(_yt_search_videos, req.query, n),
            asyncio.to_thread(_yt_search_playlists, req.query, half),
        )
    except Exception as exc:
        log.exception("search failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = {"videos": videos, "playlists": playlists}
    _search_cache.set(cache_key, result)
    log.info("search done: %d videos, %d playlists", len(videos), len(playlists))
    return result


def _yt_search_videos(query: str, n: int) -> list[dict]:
    """Fast video search via yt-dlp flat extraction (no per-video metadata fetch)."""
    from yt_dlp import YoutubeDL  # noqa: PLC0415

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)

    out: list[dict] = []
    for e in info.get("entries", []) or []:
        vid = e.get("id") or ""
        thumbs = e.get("thumbnails") or []
        thumb = thumbs[-1].get("url", "") if thumbs else ""
        if not thumb and vid:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        out.append({
            "type": "video",
            "url": e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
            "title": e.get("title", ""),
            "channel": e.get("uploader") or e.get("channel") or "",
            "duration": _fmt_duration(e.get("duration")),
            "thumbnail": thumb,
        })
    return out


def _yt_search_playlists(query: str, n: int) -> list[dict]:
    """Playlist search. Best-effort: failures must not break video results."""
    try:
        from youtubesearchpython import PlaylistsSearch  # noqa: PLC0415

        ps = PlaylistsSearch(query, limit=n).result()
        return [
            {
                "type": "playlist",
                "url": p["link"],
                "title": p.get("title", ""),
                "thumbnail": ((p.get("thumbnails") or [{}])[0]).get("url", ""),
            }
            for p in ps.get("result", [])
        ]
    except Exception as exc:
        log.warning("playlist search failed: %s", exc)
        return []


_UNAVAILABLE_TITLES = frozenset({"[Private video]", "[Deleted video]"})


def _check_url_available(url: str) -> str | None:
    """Return an error string if the URL is unavailable, None if ok.

    Uses skip_download so no file is written — this is just a metadata probe.
    """
    from yt_dlp import YoutubeDL, utils  # noqa: PLC0415

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info is None or info.get("title") in _UNAVAILABLE_TITLES:
            return "Video unavailable."
        return None
    except utils.DownloadError as exc:
        return _strip_ansi(str(exc))
    except Exception as exc:  # noqa: BLE001
        return str(exc)


@app.post("/api/playlist-info")
async def playlist_info(req: PlaylistInfoRequest):
    from yt_dlp import YoutubeDL  # noqa: PLC0415

    log.info("playlist-info url=%r", req.url)

    def _fetch():
        opts = {"extract_flat": True, "quiet": True, "no_warnings": True,
                "ignoreerrors": True,
                "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}}}
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(req.url, download=False)

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        log.error("playlist-info failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Keep index aligned with the true 1-based playlist position so
    # selected_items maps correctly to yt-dlp's playlist_items on download.
    # Unavailable entries (None or known-unavailable titles) are included but
    # marked available=False so the UI can show them grayed/unchecked.
    entries = []
    for i, entry in enumerate(data.get("entries", []), 1):
        if entry is None:
            entries.append({"index": i, "title": "[Unavailable]", "available": False})
        elif entry.get("title") in _UNAVAILABLE_TITLES:
            entries.append({"index": i, "title": entry["title"], "available": False})
        else:
            entries.append({"index": i, "title": entry.get("title") or f"Track {i}", "available": True})

    unavailable = sum(1 for e in entries if not e["available"])
    log.info("playlist-info done: %d entries, %d unavailable", len(entries), unavailable)
    return {"entries": entries}


# ---------------- downloads (resumable jobs) ----------------

@app.post("/api/download")
async def download(req: DownloadRequest):
    """Create a background download job and return its id immediately.

    The job runs independently of any HTTP connection, so closing the page does
    not stop it. Clients watch progress via GET /api/download/{job_id}/events.
    """
    # For single-video downloads, probe availability before creating the job so
    # the user gets an instant error rather than a full download attempt that
    # fails at the very end.
    if not req.playlist:
        err = await asyncio.to_thread(_check_url_available, req.url)
        if err:
            raise HTTPException(status_code=400, detail=err)

    job_id = uuid.uuid4().hex
    total = len(req.selected_items) if req.playlist and req.selected_items else 1
    db.create_download(
        _conn, job_id, req.url,
        title=req.title or None, artist=req.artist or None, album=req.album or None,
        playlist=req.playlist, total=total,
    )
    log.info(
        "download job=%s url=%r artist=%r album=%r playlist=%s",
        job_id, req.url, req.artist, req.album, req.playlist,
    )
    asyncio.create_task(_run_job(job_id, req))
    return {"job_id": job_id}


@app.get("/api/downloads")
async def downloads():
    return db.list_downloads(_conn)


@app.get("/api/download/{job_id}")
async def download_state(job_id: str):
    state = db.get_download(_conn, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="job not found")
    return state


@app.delete("/api/download/{job_id}")
async def cancel_download(job_id: str):
    state = db.get_download(_conn, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="job not found")
    _cancelled.add(job_id)
    return {"ok": True}


@app.get("/api/download/{job_id}/events")
async def download_events(job_id: str):
    state = db.get_download(_conn, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="job not found")

    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(job_id, set()).add(q)

    async def gen():
        try:
            # Replay current state so a returning client sees where things are.
            yield _sse("snapshot", json.dumps(state))
            if state["status"] in ("done", "error", "cancelled"):
                if state["status"] == "done":
                    yield _sse("done", "")
                elif state["status"] == "cancelled":
                    yield _sse("cancelled", "")
                else:
                    yield _sse("failed", state.get("error") or "failed")
                return
            while True:
                item = await q.get()
                yield _sse(item["event"], item["data"])
                if item["event"] in ("done", "failed", "cancelled"):
                    break
        finally:
            _subscribers.get(job_id, set()).discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_job(job_id: str, req: DownloadRequest) -> None:
    try:
        await _run_download(job_id, req)
    except Exception as exc:  # never let a job crash the loop silently
        log.exception("job %s crashed: %s", job_id, exc)
        _emit(job_id, "failed", str(exc))
    finally:
        _cancelled.discard(job_id)


async def _run_download(job_id: str, req: DownloadRequest) -> None:
    from yt_dlp import YoutubeDL  # noqa: PLC0415
    import yt_dlp.utils  # noqa: PLC0415

    artist = req.artist.strip()
    album = req.album.strip()
    title = req.title.strip()

    def _safe(s: str) -> str:
        """Strip characters that would split a path component."""
        return s.replace("/", "-").replace("\0", "")

    if req.playlist:
        dirname = f"{_safe(artist)}-{_safe(album)}" if artist and album else _safe(artist or album or "playlist")
        savedir = SAVE_DIR / dirname
        output_template = "%(autonumber)02d-%(title)s"
    else:
        dirname = _safe(artist) if artist else "unknown"
        savedir = SAVE_DIR / dirname
        output_template = title if title else "%(title)s"

    savedir.mkdir(parents=True, exist_ok=True)
    db.update_download(_conn, job_id, savedir=str(savedir))
    before_files = set(savedir.glob("*.m4a"))

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()
    state = {"done": 0, "total": len(req.selected_items) if req.playlist and req.selected_items else 1}

    def on_item_error(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "warn", "msg": msg})

    def on_status(msg: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "status", "msg": msg})

    def progress_hook(d):
        if job_id in _cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        status = d.get("status")
        if status == "finished":
            state["done"] += 1
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", "done": state["done"], "total": state["total"]},
            )
        elif status == "error":
            err = _strip_ansi(str(d.get("error", "item failed")))
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "warn", "msg": err})

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "extractor_args": {"youtube": {"player_client": ["tv_embedded"]}},
        "noplaylist": not req.playlist,
        "outtmpl": output_template,
        "paths": {"home": str(savedir)},
        # Extract audio to m4a AND fetch+convert the thumbnail to a sibling .jpg.
        # Art is embedded afterwards via mutagen (reliable, no AtomicParsley needed).
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
        ],
        "ignoreerrors": True,
        "logger": _Logger(on_item_error, on_status),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
    }

    if req.playlist and req.selected_items:
        ydl_opts["playlist_items"] = ",".join(str(i) for i in req.selected_items)

    error_holder: list[str] = []
    cancelled_holder: list[bool] = []

    def run():
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([req.url])
        except yt_dlp.utils.DownloadCancelled:
            cancelled_holder.append(True)
        except yt_dlp.utils.DownloadError as exc:
            error_holder.append(_strip_ansi(str(exc)))
        except Exception as exc:
            error_holder.append(str(exc))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "_done"})

    _emit(job_id, "status", "Downloading...")
    task = asyncio.create_task(asyncio.to_thread(run))

    while True:
        event = await queue.get()
        if event["type"] == "_done":
            break
        elif event["type"] == "progress":
            _emit(job_id, "progress", json.dumps({"done": event["done"], "total": event["total"]}))
        elif event["type"] == "status":
            _emit(job_id, "status", event["msg"])
        elif event["type"] == "warn":
            log.warning("download warn: %s", event["msg"])
            _publish(job_id, "warn", event["msg"])

    await task

    if cancelled_holder:
        _emit(job_id, "cancelled", "")
        return

    if error_holder:
        log.error("download failed: %s", error_holder[0])
        _emit(job_id, "failed", error_holder[0])
        return

    # Ensure bar always reaches 100%
    if state["done"] < state["total"]:
        _emit(job_id, "progress", json.dumps({"done": state["total"], "total": state["total"]}))

    # Probe, tag, and embed artwork for newly downloaded files.
    new_files = sorted(set(savedir.glob("*.m4a")) - before_files)

    # ignoreerrors=True lets a playlist skip bad entries, but it also means a
    # single private/removed video finishes with no files. Don't fake success.
    if not new_files:
        msg = "No tracks downloaded (video may be private, removed, or unavailable)."
        log.error("download produced no files: job=%s url=%s", job_id, req.url)
        _emit(job_id, "failed", msg)
        return

    cover_written = artwork.has_folder_cover(savedir)
    for f in new_files:
        probe_err = await _probe_file(f)
        if probe_err:
            log.warning("probe failed for %s: %s", f.name, probe_err)
            _publish(job_id, "warn", f"{f.name}: {probe_err}")

        # 1) Write text metadata via ffmpeg (re-mux, copy streams).
        file_meta: list[str] = []
        if req.playlist:
            parts = f.stem.split("-", 1)
            track_title = parts[1].strip() if len(parts) == 2 else f.stem
            track_num = parts[0].strip()
            if track_title:
                file_meta += ["-metadata", f"title={track_title}"]
            if track_num.isdigit():
                file_meta += ["-metadata", f"track={int(track_num)}"]
        else:
            file_meta += ["-metadata", f"title={title or f.stem}"]
        if artist:
            file_meta += ["-metadata", f"artist={artist}", "-metadata", f"album_artist={artist}"]
        if album:
            file_meta += ["-metadata", f"album={album}"]

        _emit(job_id, "status", f"Tagging {f.name}...")
        tmp = f.with_suffix(".tmp.m4a")
        cmd = ["ffmpeg", "-y", "-i", str(f)] + file_meta + ["-c", "copy", str(tmp)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await proc.wait() == 0:
            tmp.replace(f)
        else:
            tmp.unlink(missing_ok=True)
            log.warning("metadata write failed for %s", f.name)
            _publish(job_id, "warn", f"{f.name}: metadata write failed")

        # 2) Embed cover art LAST (after the re-mux) so nothing strips it, and
        #    drop one cover.jpg in the album dir for OwnTone/folder-art fallback.
        thumb = f.with_suffix(".jpg")
        if thumb.exists():
            data = thumb.read_bytes()
            if not artwork.embed_art(f, "image/jpeg", data):
                _publish(job_id, "warn", f"{f.name}: cover embed failed")
            if not cover_written:
                artwork.write_folder_cover(savedir, data, ".jpg")
                cover_written = True
            thumb.unlink(missing_ok=True)

    if not req.playlist and req.delay:
        _emit(job_id, "status", "Trimming silence...")
        m4a_files = sorted(savedir.glob("*.m4a"))
        dst = m4a_files[0] if m4a_files else None
        if dst and dst.exists():
            tmp = dst.with_suffix(".tmp.m4a")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(dst), "-ss", str(req.delay), "-c", "copy", str(tmp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await proc.wait() == 0:
                tmp.replace(dst)
            else:
                tmp.unlink(missing_ok=True)
                _emit(job_id, "failed", "delay trim failed")
                return

    if req.playlist:
        m3u_path = savedir / f"{dirname}.m3u"
        m3u_path.write_text("\n".join(str(f) for f in sorted(savedir.glob("*.m4a"))) + "\n")

    log.info("download done: job=%s savedir=%s", job_id, savedir)
    _emit(job_id, "done", "")


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

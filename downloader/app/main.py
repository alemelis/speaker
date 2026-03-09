import asyncio
import json
import logging
import os
import re
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
    log.info("playlist-info url=%r", req.url)
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--flat-playlist", "-J", "--no-warnings", req.url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")
        log.error("playlist-info failed: %s", err)
        raise HTTPException(status_code=400, detail=err)
    data = json.loads(stdout)
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

    metadata = ["--embed-metadata", "--embed-thumbnail"]
    ffmpeg_args = []

    if artist:
        safe = artist.replace('"', '\\"')
        ffmpeg_args += [f'-metadata artist="{safe}"', f'-metadata album_artist="{safe}"']
    if album:
        safe = album.replace('"', '\\"')
        ffmpeg_args.append(f'-metadata album="{safe}"')
    if not req.playlist and title:
        safe = title.replace('"', '\\"')
        ffmpeg_args.append(f'-metadata title="{safe}"')

    if ffmpeg_args:
        metadata.extend(["--postprocessor-args", f"Metadata:{' '.join(ffmpeg_args)}"])

    if req.playlist:
        metadata.extend(["--parse-metadata", "autonumber:%(track_number)s"])
    else:
        metadata.extend(["--parse-metadata", "1:%(track_number)s"])

    cmd = ["yt-dlp", "--yes-playlist" if req.playlist else "--no-playlist"]

    if req.playlist and req.selected_items:
        cmd.extend(["--playlist-items", ",".join(str(i) for i in req.selected_items)])

    cmd += ["-x", "--audio-format", "m4a", "-P", str(savedir), "-o", output_template, *metadata, req.url]

    total = len(req.selected_items) if req.playlist and req.selected_items else 1
    done = 0
    log_lines: list[str] = []
    dst: Path | None = None
    # matches "[download] Downloading item 3 of 13"
    _item_re = re.compile(r"\[download\] Downloading item (\d+) of (\d+)")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    assert process.stdout is not None
    async for raw in process.stdout:
        line = raw.decode(errors="replace").rstrip()
        log_lines.append(line)
        log.debug("yt-dlp: %s", line)
        if req.playlist:
            # "Downloading item N of M" fires at the start of each item;
            # when we see item N > 1 starting, item N-1 just finished.
            m = _item_re.search(line)
            if m:
                n = int(m.group(1))
                if n > 1 and n - 1 > done:
                    done = n - 1
                    yield _sse("progress", json.dumps({"done": done, "total": total}))
        else:
            if line.startswith("[ExtractAudio] Destination:"):
                dst = Path(line.split(":", 1)[1].strip())
                done += 1
                yield _sse("progress", json.dumps({"done": done, "total": total}))
            elif line.startswith("[ExtractAudio] Not converting audio"):
                dst = Path(line.split(";")[0].split()[-1].strip())
                done += 1
                yield _sse("progress", json.dumps({"done": done, "total": total}))

    await process.wait()

    if process.returncode != 0:
        log.error("download failed (rc=%d):\n%s", process.returncode, "\n".join(log_lines))
        yield _sse("error", "\n".join(log_lines))
        return

    # Ensure bar always reaches 100% regardless of which yt-dlp lines were seen
    if req.playlist and done < total:
        yield _sse("progress", json.dumps({"done": total, "total": total}))

    if req.playlist:
        m3u_path = savedir / f"{dirname}.m3u"
        m3u_path.write_text("\n".join(str(f) for f in sorted(savedir.glob("*.m4a"))) + "\n")

    if not req.playlist and req.delay and dst and dst.exists():
        tmp = Path("/tmp/temp_audio.m4a")
        proc2 = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", str(dst), "-ss", str(req.delay), "-c", "copy", str(tmp),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc2.stdout is not None
        trim_log: list[str] = []
        async for raw in proc2.stdout:
            trim_log.append(raw.decode(errors="replace").rstrip())
        await proc2.wait()
        if proc2.returncode == 0:
            tmp.replace(dst)
        else:
            yield _sse("error", "\n".join(trim_log))
            return

    log.info("download done: %s", dst)
    yield _sse("done", "")


app.mount("/", SPAStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

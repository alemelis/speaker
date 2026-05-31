"""MPD filter-proxy for OwnTone.

OwnTone's MPD-protocol layer implements only a subset of tags. Clients like
MPD Pilot send `list ... group musicbrainz_albumid ...`, and OwnTone rejects the
*entire* command over that one unsupported token (ACK_ERROR_ARG), which breaks
album browsing completely.

This proxy sits between the client and OwnTone: it forwards everything verbatim
except it strips `group <tag>` pairs whose tag OwnTone does not support, so the
command becomes one OwnTone accepts. Server -> client bytes (including binary
albumart) pass through untouched.

Pure stdlib; no dependencies.
"""

import asyncio
import contextlib
import logging
import os
import re

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("mpd-proxy")

LISTEN_HOST = os.environ.get("MPD_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("MPD_PROXY_PORT", "6601"))
UPSTREAM_HOST = os.environ.get("MPD_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.environ.get("MPD_UPSTREAM_PORT", "6600"))

# Tags OwnTone 29.0 advertises via `tagtypes` and accepts in `group`.
SUPPORTED_GROUP_TAGS = {
    "artist", "artistsort", "albumartist", "albumartistsort",
    "album", "albumsort", "title", "titlesort", "genre",
    "composer", "composersort", "track", "disc", "date",
    "performer", "comment", "label", "originaldate",  # harmless extras
}

# `group TAG` or `group "TAG"` (MPD tag names are letters/underscores).
_GROUP_RE = re.compile(r'\s+group\s+("?)([A-Za-z_]+)\1', re.IGNORECASE)


def sanitize(line: str) -> str:
    """Strip `group <tag>` pairs whose tag OwnTone can't handle."""
    def repl(m: re.Match) -> str:
        tag = m.group(2).lower()
        return "" if tag not in SUPPORTED_GROUP_TAGS else m.group(0)

    return _GROUP_RE.sub(repl, line)


async def pump_client_to_upstream(
    creader: asyncio.StreamReader, uwriter: asyncio.StreamWriter, peer: str
) -> None:
    """Client commands are newline-terminated text; rewrite per line."""
    try:
        while True:
            raw = await creader.readline()
            if not raw:
                break
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                uwriter.write(raw)
                await uwriter.drain()
                continue
            line = text.rstrip("\r\n")
            new = sanitize(line)
            if new != line:
                log.info("[%s] rewrote: %r -> %r", peer, line, new.strip())
            uwriter.write((new + "\n").encode("utf-8"))
            await uwriter.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        with contextlib.suppress(Exception):
            uwriter.write_eof()


async def pump_upstream_to_client(
    ureader: asyncio.StreamReader, cwriter: asyncio.StreamWriter
) -> None:
    """Server responses may contain binary (albumart) -> raw passthrough."""
    try:
        while True:
            chunk = await ureader.read(65536)
            if not chunk:
                break
            cwriter.write(chunk)
            await cwriter.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass


async def handle_client(creader: asyncio.StreamReader, cwriter: asyncio.StreamWriter) -> None:
    peer = "?"
    try:
        peername = cwriter.get_extra_info("peername")
        peer = f"{peername[0]}:{peername[1]}" if peername else "?"
    except Exception:
        pass

    try:
        ureader, uwriter = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except OSError as exc:
        log.error("[%s] cannot reach OwnTone MPD %s:%s: %s", peer, UPSTREAM_HOST, UPSTREAM_PORT, exc)
        cwriter.close()
        return

    log.info("[%s] connected", peer)
    t1 = asyncio.create_task(pump_client_to_upstream(creader, uwriter, peer))
    t2 = asyncio.create_task(pump_upstream_to_client(ureader, cwriter))
    done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    for w in (uwriter, cwriter):
        with contextlib.suppress(Exception):
            w.close()
    log.info("[%s] closed", peer)


async def main() -> None:
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    log.info(
        "MPD filter-proxy listening on %s:%s -> %s:%s",
        LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

"""Fetch missing album art from the Cover Art Archive (MusicBrainz).

For albums that have no embedded art and no folder cover (typically YouTube
downloads), look the release up on MusicBrainz by artist/album, grab the front
cover from the Cover Art Archive, then write cover.jpg and embed it into the
audio files so OwnTone serves it over HTTP *and* MPD (albumart/readpicture).

Run with: python -m core.artfetch
"""

import time
from pathlib import Path

import requests

from . import artwork, config
from .owntone import OwnToneClient

AUDIO_SUFFIXES = {".m4a", ".mp3", ".flac", ".ogg", ".opus"}
USER_AGENT = "FOMO-jukebox/1.0 (https://github.com/alemelis; alessandro_melis@rocketmail.com)"
MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"
MB_MIN_SCORE = 85  # ignore weak matches to avoid wrong covers
MB_RATE_LIMIT_S = 1.1  # MusicBrainz asks for <= 1 req/s

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


def _audio_files(directory: Path) -> list[Path]:
    return [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES]


def parse_dirname(name: str) -> tuple[str, str]:
    """'Artist-Album' -> (artist, album). No dash -> ('', name)."""
    if "-" in name:
        artist, album = name.split("-", 1)
        return artist.strip(), album.strip()
    return "", name.strip()


def _meta_from_tags(audio: list[Path]) -> tuple[str, str]:
    """Read albumartist/album from the first audio file's tags.

    Falls back to parse_dirname on the folder name if tags are missing.
    Tags are the ground truth — folder names can be wrong after a rename.
    """
    try:
        from mutagen import File as MutagenFile  # noqa: PLC0415
        tags = MutagenFile(audio[0], easy=True)
        if tags and tags.tags:
            def _first(key: str) -> str:
                v = tags.tags.get(key, [])
                val = v[0] if isinstance(v, list) else v
                return str(val).strip() if val else ""
            artist = _first("albumartist") or _first("artist")
            album  = _first("album")
            if artist and album:
                return artist, album
    except Exception:
        pass
    return parse_dirname(audio[0].parent.name)


def _mb_release_group_id(artist: str, album: str) -> str | None:
    if album and artist:
        query = f'releasegroup:"{album}" AND artist:"{artist}"'
    elif album:
        query = f'releasegroup:"{album}"'
    else:
        return None
    resp = _session.get(
        f"{MB_BASE}/release-group",
        params={"query": query, "fmt": "json", "limit": 5},
        timeout=20,
    )
    time.sleep(MB_RATE_LIMIT_S)
    if resp.status_code != 200:
        return None
    groups = resp.json().get("release-groups", [])
    if not groups:
        return None
    best = groups[0]
    if best.get("score", 0) < MB_MIN_SCORE:
        return None
    return best.get("id")


def _caa_front(rg_id: str) -> bytes | None:
    """Front cover for a release-group, following CAA redirects to the image."""
    resp = _session.get(f"{CAA_BASE}/release-group/{rg_id}", timeout=20, allow_redirects=True)
    if resp.status_code != 200:
        return None
    images = resp.json().get("images", [])
    front = next((i for i in images if i.get("front")), images[0] if images else None)
    if not front:
        return None
    # Prefer a reasonably sized thumbnail over a multi-MB original.
    url = front.get("thumbnails", {}).get("500") or front.get("image")
    img = _session.get(url, timeout=30)
    if img.status_code != 200 or not img.content:
        return None
    return img.content


def fetch_cover(artist: str, album: str) -> bytes | None:
    rg_id = _mb_release_group_id(artist, album)
    if not rg_id:
        return None
    return _caa_front(rg_id)


def backfill_missing(music_root: Path) -> dict[str, int]:
    stats = {"checked": 0, "fetched": 0, "skipped_have_art": 0, "no_match": 0}

    for dirpath in sorted(p for p in music_root.iterdir() if p.is_dir()):
        audio = _audio_files(dirpath)
        if not audio:
            continue
        stats["checked"] += 1

        has_cover = artwork.find_folder_cover(dirpath) is not None
        has_embed = any(artwork.read_embedded_art(f) is not None for f in audio[:1])
        if has_cover or has_embed:
            stats["skipped_have_art"] += 1
            continue

        artist, album = _meta_from_tags(audio)
        print(f"  looking up: artist={artist!r} album={album!r}")
        data = fetch_cover(artist, album)
        if data is None:
            stats["no_match"] += 1
            print(f"    no cover found -> {dirpath.name}")
            continue

        artwork.write_folder_cover(dirpath, data, ".jpg")
        embedded = 0
        for f in audio:
            if artwork.embed_art(f, "image/jpeg", data):
                embedded += 1
        stats["fetched"] += 1
        print(f"    wrote cover.jpg + embedded into {embedded}/{len(audio)} files")

    return stats


if __name__ == "__main__":
    root = config.MUSIC_ROOT
    print(f"Scanning {root} for albums with no art ...")
    stats = backfill_missing(root)
    print(
        f"\nDone. checked={stats['checked']}  fetched={stats['fetched']}  "
        f"already_had_art={stats['skipped_have_art']}  no_match={stats['no_match']}"
    )
    print("Triggering OwnTone rescan ...")
    result = OwnToneClient().rescan()
    print(f"  ok={result['ok']}  endpoint={result['endpoint']}  message={result['message']}")

"""Backfill album art across the FOMO music library.

Walk MUSIC_ROOT looking for album directories (dirs containing audio files).
For each album dir:
  - If a folder cover exists but some audio files lack embedded art, embed it.
  - Else if no folder cover exists but an audio file has embedded art, extract
    and write cover.jpg.
Run with: python -m core.backfill
"""

from pathlib import Path

from . import artwork, config
from .owntone import OwnToneClient

AUDIO_SUFFIXES = {".m4a", ".mp3", ".flac", ".ogg", ".opus"}


def _audio_files(directory: Path) -> list[Path]:
    return [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES]


def _mime_from_ext(ext: str) -> str:
    return "image/png" if ext.lower() in (".png",) else "image/jpeg"


def backfill(music_root: Path) -> dict[str, int]:
    stats = {"dirs_scanned": 0, "covers_written": 0, "files_embedded": 0}

    for dirpath in sorted(music_root.rglob("*")):
        if not dirpath.is_dir():
            continue
        audio = _audio_files(dirpath)
        if not audio:
            continue

        stats["dirs_scanned"] += 1
        cover_path = artwork.find_folder_cover(dirpath)

        if cover_path is not None:
            # Embed folder cover into audio files that lack embedded art.
            cover_data = cover_path.read_bytes()
            mime = _mime_from_ext(cover_path.suffix)
            for f in audio:
                if artwork.read_embedded_art(f) is None:
                    if artwork.embed_art(f, mime, cover_data):
                        stats["files_embedded"] += 1
                        print(f"  embedded art -> {f.relative_to(music_root)}")
        else:
            # No folder cover; try to extract from an audio file.
            for f in audio:
                result = artwork.read_embedded_art(f)
                if result is not None:
                    mime, data = result
                    ext = ".png" if "png" in mime else ".jpg"
                    dest = artwork.write_folder_cover(dirpath, data, ext)
                    stats["covers_written"] += 1
                    print(f"  wrote cover  -> {dest.relative_to(music_root)}")
                    break  # one cover per dir is enough

    return stats


if __name__ == "__main__":
    music_root = config.MUSIC_ROOT
    print(f"Scanning {music_root} ...")
    stats = backfill(music_root)
    print(
        f"\nDone. dirs_scanned={stats['dirs_scanned']}  "
        f"covers_written={stats['covers_written']}  "
        f"files_embedded={stats['files_embedded']}"
    )
    print("Triggering OwnTone rescan ...")
    result = OwnToneClient().rescan()
    print(f"  ok={result['ok']}  endpoint={result['endpoint']}  message={result['message']}")

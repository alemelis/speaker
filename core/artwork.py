"""Album-art helpers: read embedded covers, write folder cover.jpg, embed art.

OwnTone shows artwork from embedded tags AND from a folder image (cover.jpg /
folder.jpg). The downloader now embeds art via yt-dlp's EmbedThumbnail and also
drops a cover.jpg per album dir using `write_folder_cover`. The backfill script
uses `read_embedded_art` + `write_folder_cover` (and `embed_art`) to repair the
existing library so covers appear in every client.
"""

from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4, MP4Cover

FOLDER_COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png")


def has_folder_cover(album_dir: Path) -> bool:
    return any((album_dir / name).exists() for name in FOLDER_COVER_NAMES)


def find_folder_cover(album_dir: Path) -> Path | None:
    for name in FOLDER_COVER_NAMES:
        p = album_dir / name
        if p.exists():
            return p
    return None


def write_folder_cover(album_dir: Path, data: bytes, ext: str = ".jpg") -> Path:
    """Write cover image bytes as cover<ext> in the album directory."""
    album_dir.mkdir(parents=True, exist_ok=True)
    dest = album_dir / f"cover{ext.lower()}"
    dest.write_bytes(data)
    return dest


def read_embedded_art(path: Path) -> tuple[str, bytes] | None:
    """Return (mime, data) of the first embedded picture, or None."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".flac":
            flac = FLAC(path)
            if flac.pictures:
                pic = flac.pictures[0]
                return pic.mime or "image/jpeg", pic.data
        elif suffix == ".mp3":
            tags = ID3(path)
            apics = tags.getall("APIC")
            if apics:
                return apics[0].mime or "image/jpeg", apics[0].data
        elif suffix in (".m4a", ".mp4", ".m4b"):
            mp4 = MP4(path)
            covers = mp4.tags.get("covr") if mp4.tags else None
            if covers:
                cover = covers[0]
                mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
                return mime, bytes(cover)
        else:
            audio = MutagenFile(path)
            pics = getattr(audio, "pictures", None) if audio else None
            if pics:
                return pics[0].mime or "image/jpeg", pics[0].data
    except Exception:
        return None
    return None


def embed_art(path: Path, mime: str, data: bytes) -> bool:
    """Embed cover art into an audio file. Returns True on success."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".flac":
            flac = FLAC(path)
            pic = Picture()
            pic.type = 3  # front cover
            pic.mime = mime
            pic.data = data
            flac.clear_pictures()
            flac.add_picture(pic)
            flac.save()
        elif suffix == ".mp3":
            try:
                tags = ID3(path)
            except Exception:
                tags = ID3()
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            tags.save(path)
        elif suffix in (".m4a", ".mp4", ".m4b"):
            mp4 = MP4(path)
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            mp4.setdefault("covr", [])
            mp4["covr"] = [MP4Cover(data, imageformat=fmt)]
            mp4.save()
        else:
            return False
    except Exception:
        return False
    return True

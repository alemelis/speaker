from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from mutagen import File as MutagenFile

SUPPORTED_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus"}
EDITABLE_FIELDS = {
    "album",
    "albumartist",
    "artist",
    "title",
    "tracknumber",
    "discnumber",
    "compilation",
    "date",
}


def _first_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _normalize_write_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def validate_path(path_value: str, music_root: Path) -> Path:
    root = music_root.resolve()
    input_path = Path(path_value)
    candidate = input_path if input_path.is_absolute() else (root / input_path)
    resolved = candidate.resolve()

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path is outside MUSIC_ROOT.",
        ) from exc

    if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension: {resolved.suffix}",
        )

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track file not found.",
        )

    return resolved


def read_minimal_tags(abs_path: Path, music_root: Path) -> dict[str, Any]:
    audio = MutagenFile(abs_path, easy=True)
    if audio is None:
        raise ValueError(f"Unsupported or unreadable file: {abs_path}")

    tags = audio.tags or {}
    rel_path = str(abs_path.resolve().relative_to(music_root.resolve()))
    return {
        "path": rel_path,
        "title": _first_value(tags.get("title")),
        "artist": _first_value(tags.get("artist")),
        "album": _first_value(tags.get("album")),
        "albumartist": _first_value(tags.get("albumartist")),
        "tracknumber": _first_value(tags.get("tracknumber")),
        "discnumber": _first_value(tags.get("discnumber")),
    }


def read_tags(abs_path: Path, music_root: Path) -> dict[str, Any]:
    audio = MutagenFile(abs_path, easy=True)
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported or unreadable file format.",
        )

    rel_path = str(abs_path.resolve().relative_to(music_root.resolve()))
    raw_tags = audio.tags or {}
    tags = {key: _first_value(value) for key, value in raw_tags.items()}

    return {
        "path": rel_path,
        "format": audio.mime[0] if getattr(audio, "mime", None) else None,
        "tags": tags,
    }


def write_tags(abs_path: Path, tags: dict[str, Any]) -> None:
    audio = MutagenFile(abs_path, easy=True)
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported or unreadable file format.",
        )

    for key, value in tags.items():
        if key not in EDITABLE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported editable field: {key}",
            )

        if value is None:
            if audio.tags and key in audio.tags:
                del audio.tags[key]
            continue

        write_value = _normalize_write_value(value)
        audio[key] = [write_value]

    audio.save()

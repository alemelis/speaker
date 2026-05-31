from pathlib import Path
from threading import Lock
from typing import Any

from .metadata import SUPPORTED_EXTENSIONS, read_minimal_tags, validate_path

_index: list[dict[str, Any]] = []
_index_lock = Lock()


def _scan_library(music_root: Path) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    root = music_root.resolve()

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            tracks.append(read_minimal_tags(file_path, root))
        except Exception:
            # A single corrupt or unsupported file should not break indexing.
            continue

    return tracks


def rebuild(music_root: Path) -> int:
    tracks = _scan_library(music_root)
    with _index_lock:
        _index.clear()
        _index.extend(tracks)
    return len(tracks)


def get_index() -> list[dict[str, Any]]:
    with _index_lock:
        return list(_index)


def update_one(path_value: str, music_root: Path) -> None:
    abs_path = validate_path(path_value, music_root)
    updated = read_minimal_tags(abs_path, music_root)

    with _index_lock:
        for idx, item in enumerate(_index):
            if item["path"] == updated["path"]:
                _index[idx] = updated
                break
        else:
            _index.append(updated)


def remove_one(path_value: str) -> None:
    rel = str(Path(path_value))
    with _index_lock:
        for idx, item in enumerate(_index):
            if item["path"] == rel:
                del _index[idx]
                break

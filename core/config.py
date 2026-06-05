"""Single, typed place for all FOMO environment configuration.

Previously each service loaded these independently with inconsistent defaults
(e.g. FOMO_DB was "./fomo.db" in the daemon but "/data/fomo.db" in the UIs,
and OWNTONE_API had no default at all). This module is the one canonical view.
"""

import os
from pathlib import Path

# SQLite database shared by all services (tags, plays, downloads).
FOMO_DB: str = os.getenv("FOMO_DB", "/data/fomo.db")

# OwnTone API base URL. Includes the "/api" suffix (e.g. http://host:3689/api).
# The OwnTone client normalizes a trailing slash and tolerates a missing /api.
OWNTONE_API: str = os.getenv("OWNTONE_API", "http://localhost:3689/api").rstrip("/")

# Music library root that OwnTone serves and the metadata editor scans.
MUSIC_ROOT: Path = Path(os.getenv("MUSIC_ROOT", "/music"))

# Where the downloader writes new tracks (usually the same as MUSIC_ROOT).
SAVE_DIR: Path = Path(os.getenv("SAVE_DIR", os.getenv("MUSIC_ROOT", "/music")))

# Name of the rfid-daemon container, used by the tags UI to scrape unknown-tag logs.
RFID_CONTAINER: str = os.getenv("RFID_CONTAINER", "rfid-daemon")

# Comma-separated substrings used to identify the USB NFC reader by device name.
# Configurable so a new reader doesn't require a code change.
NFC_DEVICE_MATCH: tuple[str, ...] = tuple(
    s.strip() for s in os.getenv("NFC_DEVICE_MATCH", "Van Ooijen,RFID").split(",") if s.strip()
)

# Discover feature — free key at last.fm/api/account/create
LASTFM_API_KEY: str = os.getenv("LASTFM_API_KEY", "")

# Discogs personal access token — https://www.discogs.com/settings/developers
# Used as a fallback artwork source when MusicBrainz/CAA has no cover.
DISCOGS_TOKEN: str = os.getenv("DISCOGS_TOKEN", "")

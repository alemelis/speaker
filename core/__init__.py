"""FOMO shared core: config, OwnTone client, SQLite, artwork, web helpers.

This package is the single source of truth shared by the NFC daemon and the
web app. Both Docker images copy it to /app/core (build context is the repo
root), so `from core import ...` works in every service.
"""

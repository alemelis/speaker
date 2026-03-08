# FOMO sound-system

## dashboard

```
uv venv
source .venv/bin/activate
uvx streamlit run dash.py
```


## daemon

```
docker compose up -d
```


## metadata-webui

Metadata editor for Owntone library files (served on port `3030`).

Environment variables used by this service:

- `ST_SAVE_DIR`: host path mounted into the container as `/music`
- `OWNTONE_API`: same variable used by daemon (for example `http://pi4.local:3689/api`)

Run:

```
docker compose up -d metadata-webui
```


## tag-organizer

Simple web tool for managing RFID `tag_id -> query` mappings in `tags.yaml` (served on port `3040`).

Environment variables used by this service:

- `SPEAKER_DIR`: host path containing `tags.yaml` (mounted as `/data`)
- `OWNTONE_API`: Owntone API base used for search suggestions

Run:

```
docker compose up -d tag-organizer
```

### Serving behind nginx (e.g. pi4.local/metadata, pi4.local/tags)

Both apps use **relative** asset and API paths, so they work under a subpath. In nginx:

1. **Redirect** `/metadata` → `/metadata/` and `/tags` → `/tags/` (trailing slash required for relative URLs).
2. **Proxy** with the path stripped so the app sees requests at root:

```nginx
# Redirect without trailing slash to with trailing slash
location = /metadata { return 301 /metadata/; }
location = /tags     { return 301 /tags/; }

location /metadata/ {
    proxy_pass http://127.0.0.1:3030/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /tags/ {
    proxy_pass http://127.0.0.1:3040/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```


## telebombardo

`wifi_credentials.h`
```C
#pragma once
#define WIFI_SSID "???"
#define WIFI_PASSWORD "???"
#define OWNTONE_API "http://???:???/api"
```

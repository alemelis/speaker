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


## telebombardo

`wifi_credentials.h`
```C
#pragma once
#define WIFI_SSID "???"
#define WIFI_PASSWORD "???"
#define OWNTONE_API "http://???:???/api"
```

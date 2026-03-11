# CLAUDE.md

## Project

The FOMO sound-system project started as a way for anyone (mostly kids) to easily play music in our living room. Now it's organically growing to be an ecosystem of tools around playing music in our house. One can picture it as a juke-box plus records shop and discography organiser.

## Hardware

- raspberry-pi4 with nvme ssd 
- lots of nfc tags; one each for a song or an album
- cheap usb nfc tags reader wired to the pi4
- AppleTV to play audio on bluetooth soundbar; both with their remote for volume adjustments
- telebombardo: an esp32 device with a potentiometer for controlling owntone volume and a lcd screen to see the current track being played. This is supposed to send curl requests to the owntone server to push volume changes and fetch info. Currently work in progress.

## Stack

- Language: Python 3.x, HTML/JS, C++
- Framework: FastAPI
- Package manager: uv

## Services

- daemon.py: awaits a read from usb nfc tag reader, decode the tag id, lookup query value, send request to owntone. This runs in a docker container in a raspberry pi 4.
- owntone server running on LAN and listening for commands (enqueue, play, stop, clear queue); this can stream through AirPlay to an AppleTV on LAN. This runs at system level on the same pi and reads audio files from a nvme ssd. Since it's controlled through curl requests, it could be on a separate machine. This is currently installed on the root system, not running as a docker container.
- mdp pilot ios app when on lan to control player without nfc tags. This is installed on my phone.
- streamlit dash.py to download tracks or albums from youtube via yt-dlp. This runs inside a tmux session on the pi and it can write to the ssd monitored by owntone. The dadhboard is exposed outside via cloudflare tunnel on one of my domains.
- gonic server to expose library on ssd outside so that I can comsume it with airsonic/substreamers, again cloudflare tunnel, again installed on main system.
- metadata-webui editor for music library. Runs in docker container. Frontend accessible theough nginx on lan only
- nfc tags-organizer UI. I use this to insert a new tag:song:album to the system. Again, one docker container, for lan only use through nginx.

## Project conventions

- Environment variables are loaded via python-dotenv from .env.example
- All the components should run inside docker containers
- Use a unique docker compose for all the services
- Always seek minimal footprint when deploying
- No JS frameworks allowed, only HMTL/JS with FastAPI backend

## Implementation notes

- Use opus for the initial architecture decisions
- Use sonnet for the actual coding passes

## Things NOT to change NOR read

- pyproject.toml
- .env
- .gitignore
- tags.yaml
- wifi_credentials.h

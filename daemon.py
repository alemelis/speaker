#!/usr/bin/env python3
import yaml
import logging
import sys
import time
import requests
from evdev import list_devices, InputDevice, ecodes
import os

# ---------------- CONFIG ----------------
TAGS_FILE = os.getenv("TAGS_FILE", "./tags.yaml")
OWNTONE_API = os.getenv("OWNTONE_API")
# ----------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Load tag mappings
try:
    with open(TAGS_FILE, "r") as f:
        tag_mapping = yaml.safe_load(f)
except Exception as e:
    logging.error(f"Failed to load {TAGS_FILE}: {e}")
    sys.exit(1)

logging.info(f"Loaded {len(tag_mapping)} tags")

current_tag = None

# Keycode → digit mapping for HID keyboard emulation
KEYMAP = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    28: "ENTER"
}

# ---------------- NAVIDROME CONTROL ----------------
def stop_playback():
    logging.info("Stopping playback")
    try:
        requests.put(f"{OWNTONE_API}/player/stop")
        requests.put(f"{OWNTONE_API}/queue/clear")
    except Exception as e:
        logging.error(f"Failed to stop playback: {e}")

def start_playback(url):
    stop_playback()
    logging.info(f"Starting playback: {url}")
    try:
        r = requests.post(f"{OWNTONE_API}/queue/items/add", params={"uris": url})
        logging.info(f"Queue add response: {r.status_code}")

        requests.put(f"{OWNTONE_API}/player/play")

    except Exception as e:
        logging.error(f"Failed to add to queue: {e}")

def toggle_shuffle(val: bool):
    logging.info(f"Setting shuffle to {val}")
    try:
        requests.put(f"{OWNTONE_API}/api/player/shuffle?state={val}")
    except Exception as e:
        logging.error(f"Failed to toggle shuffle: {e}")

# ---------------- HID TAG READER ----------------
def find_rfid_device():
    devices = [InputDevice(path) for path in list_devices()]
    for dev in devices:
        if 'Van Ooijen' in dev.name or 'RFID' in dev.name:
            logging.info(f"Using device: {dev.path} ({dev.name})")
            return dev
    logging.error("RFID reader not found")
    sys.exit(1)

def read_evdev_tag(dev):
    buffer = ""
    for event in dev.read_loop():
        if event.type == ecodes.EV_KEY and event.value == 1:  # key press only
            key = event.code
            if key in KEYMAP:
                if KEYMAP[key] == "ENTER":
                    tag_id = buffer
                    buffer = ""
                    yield tag_id
                else:
                    buffer += KEYMAP[key]

# ---------------- MAIN LOOP ----------------
def main_loop():
    global current_tag
    dev = find_rfid_device()
    tag_gen = read_evdev_tag(dev)

    logging.info(tag_mapping)

    while True:
        try:
            tag_id = next(tag_gen)
            logging.info(f"Tag detected: {tag_id}")
            if tag_id != current_tag:
                url = tag_mapping.get(int(tag_id))
                if url:
                    toggle_shuffle("playlist" in url)
                    start_playback(url)
                else:
                    logging.warning(f"Unknown tag: {tag_id}")
        except StopIteration:
            pass
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logging.info("Exiting...")
        stop_playback()

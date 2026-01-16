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


# Keycode → digit mapping for HID keyboard emulation
KEYMAP = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    28: "ENTER"
}


class Player():
    def __init__(self):
        try:
            with open(TAGS_FILE, "r") as f:
                self.tags = yaml.safe_load(f)
            logging.info(f"Loaded {len(self.tags)} tags")

        except Exception as e:
            logging.error(f"Failed to load {TAGS_FILE}: {e}")
            sys.exit(1)

        self.tag = None
        self.time = time.time()

    @classmethod
    def stop_playback(cls):
        logging.info("Stopping playback")
        try:
            requests.put(f"{OWNTONE_API}/player/stop")
            requests.put(f"{OWNTONE_API}/queue/clear")
        except Exception as e:
            logging.error(f"Failed to stop playback: {e}")

    def search(self, query):
        logging.info(f"Looking for {query}")
        try:
            resp = requests.get(f"{OWNTONE_API}/search?type={query}&limit=1")
            resp.raise_for_status()  # good habit

            thing_id = resp.json()
            logging.info(thing_id)
            if "tracks" in query:
                return thing_id['tracks']["items"][0]['uri']
            return thing_id['albums']["items"][0]['uri']
        except Exception as e:
            logging.error(f"Failed to search {query}: {e}")

    def start_playback(self, url):
        self.stop_playback()
        logging.info(f"Starting playback: {url}")
        try:
            r = requests.post(f"{OWNTONE_API}/queue/items/add", params={"uris": url})
            logging.info(f"Queue add response: {r.status_code}")
            requests.put(f"{OWNTONE_API}/player/play")
        except Exception as e:
            logging.error(f"Failed to add to queue: {e}")

    def toggle_shuffle(self, val: bool):
        logging.info(f"Setting shuffle to {val}")
        try:
            requests.put(f"{OWNTONE_API}/api/player/shuffle?state={val}")
        except Exception as e:
            logging.error(f"Failed to toggle shuffle: {e}")

    def read_tag(self, tag_id):
        now = time.time()
        if tag_id != self.tag or (now - self.time > 30.0):
            self.time = time.time()
            query = self.tags.get(int(tag_id))
            url = self.search(query)
            if url:
                self.start_playback(url)
                self.tag = tag_id
            else:
                logging.warning(f"Unknown tag: {tag_id}")

class Reader():
    def __init__(self):
        devices = [InputDevice(path) for path in list_devices()]
        for dev in devices:
            if 'Van Ooijen' in dev.name or 'RFID' in dev.name:
                logging.info(f"Using device: {dev.path} ({dev.name})")
                self.dev = dev
                return
        logging.error("RFID reader not found")
        sys.exit(1)

    def tag_gen(self):
        buffer = ""
        for event in self.dev.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:  # key press only
                key = event.code
                if key in KEYMAP:
                    if KEYMAP[key] == "ENTER":
                        tag_id = buffer
                        buffer = ""
                        yield tag_id
                    else:
                        buffer += KEYMAP[key]

def main():
    reader = Reader()
    tag_gen = reader.tag_gen()

    player = Player()

    while True:
        try:
            tag_id = next(tag_gen)
            logging.info(f"Tag detected: {tag_id}")
            player.read_tag(tag_id)
        except StopIteration:
            pass
        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Exiting...")
        Player.stop_playback()

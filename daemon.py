#!/usr/bin/env python3
import logging
import os
import sys
import time

import db
import requests
from evdev import InputDevice, ecodes, list_devices

# ---------------- CONFIG ----------------
FOMO_DB = os.getenv("FOMO_DB", "./fomo.db")
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
        self.conn = db.connect(FOMO_DB)
        logging.info(f"Connected to DB: {FOMO_DB}")
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

    def enqueue(self, kind, query):
        field = "title" if kind == "track" else "album"
        expression = f'{field} is "{query}"'
        logging.info(f"Enqueueing: {expression}")
        try:
            r = requests.post(
                f"{OWNTONE_API}/queue/items/add",
                params={"expression": expression},
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            if items:
                return items[0]["id"]
            logging.warning(f"No items matched expression: {expression}")
        except Exception as e:
            logging.error(f"Failed to enqueue: {e}")
        return None

    def play_from(self, item_id):
        try:
            requests.put(f"{OWNTONE_API}/player/play", params={"item_id": item_id})
        except Exception as e:
            logging.error(f"Failed to play: {e}")

    def read_tag(self, tag_id):
        now = time.time()
        if tag_id != self.tag or (now - self.time > 30.0):
            self.time = time.time()
            row = db.get_tag(self.conn, tag_id)
            if row is None:
                logging.warning(f"Unknown tag: {tag_id}")
                return
            kind, query = row["kind"], row["query"]
            item_id = self.enqueue(kind, query)
            if item_id:
                self.play_from(item_id)
                self.tag = tag_id
                db.log_play(self.conn, tag_id, kind, query)
            else:
                logging.warning(f"No result for tag: {tag_id}")


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

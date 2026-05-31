#!/usr/bin/env python3
"""FOMO NFC daemon: read a tag, look it up, tell OwnTone to play it.

Hardened over the original: all OwnTone calls go through the shared client (with
timeouts, so the daemon can no longer hang on a slow/down server), the NFC reader
is matched by a configurable name and reconnects with backoff instead of exiting,
and the debounce guard is lock-protected against rapid double-taps.
"""

import logging
import threading
import time

from evdev import InputDevice, ecodes, list_devices

from core import config, db
from core.owntone import OwnToneClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Keycode -> digit mapping for HID keyboard emulation.
KEYMAP = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5",
    7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    28: "ENTER",
}

DEBOUNCE_SECONDS = 30.0
RECONNECT_BACKOFF_SECONDS = 3.0


class Player:
    def __init__(self) -> None:
        self.conn = db.connect(config.FOMO_DB)
        logging.info("Connected to DB: %s", config.FOMO_DB)
        self.client = OwnToneClient()
        self.tag: str | None = None
        self.time = time.time()
        self._lock = threading.Lock()

    def stop_playback(self) -> None:
        logging.info("Stopping playback")
        try:
            self.client.stop()
            self.client.clear_queue()
        except Exception as exc:
            logging.error("Failed to stop playback: %s", exc)

    def _enqueue(self, kind: str, query: str) -> str | None:
        field = "title" if kind == "track" else "album"
        expression = f'{field} is "{query}"'
        logging.info("Enqueueing: %s", expression)
        try:
            item_id = self.client.enqueue_expression(expression)
            if item_id is None:
                logging.warning("No items matched expression: %s", expression)
            return item_id
        except Exception as exc:
            logging.error("Failed to enqueue: %s", exc)
            return None

    def read_tag(self, tag_id: str) -> None:
        with self._lock:
            now = time.time()
            if tag_id == self.tag and (now - self.time) <= DEBOUNCE_SECONDS:
                return
            self.time = now

        row = db.get_tag(self.conn, tag_id)
        if row is None:
            logging.warning("Unknown tag: %s", tag_id)
            return

        kind, query = row["kind"], row["query"]
        item_id = self._enqueue(kind, query)
        if not item_id:
            logging.warning("No result for tag: %s", tag_id)
            return

        try:
            self.client.play(item_id)
        except Exception as exc:
            logging.error("Failed to play: %s", exc)
            return

        self.tag = tag_id
        db.log_play(self.conn, tag_id, kind, query)


class Reader:
    def __init__(self) -> None:
        self.dev = self._find_device()

    @staticmethod
    def _find_device() -> InputDevice:
        for path in list_devices():
            dev = InputDevice(path)
            if any(m in dev.name for m in config.NFC_DEVICE_MATCH):
                logging.info("Using device: %s (%s)", dev.path, dev.name)
                return dev
        raise FileNotFoundError(
            f"No NFC reader matching {config.NFC_DEVICE_MATCH} found"
        )

    def tag_gen(self):
        buffer = ""
        for event in self.dev.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:  # key press only
                key = event.code
                if key in KEYMAP:
                    if KEYMAP[key] == "ENTER":
                        tag_id, buffer = buffer, ""
                        if tag_id:
                            yield tag_id
                    else:
                        buffer += KEYMAP[key]


def main() -> None:
    player = Player()
    try:
        while True:
            try:
                reader = Reader()
            except FileNotFoundError as exc:
                logging.error("%s; retrying in %ss", exc, RECONNECT_BACKOFF_SECONDS)
                time.sleep(RECONNECT_BACKOFF_SECONDS)
                continue

            try:
                for tag_id in reader.tag_gen():
                    logging.info("Tag detected: %s", tag_id)
                    player.read_tag(tag_id)
                logging.warning("Reader stream ended; reconnecting")
            except OSError as exc:
                logging.error("Reader disconnected (%s); reconnecting", exc)
            time.sleep(RECONNECT_BACKOFF_SECONDS)
    except KeyboardInterrupt:
        logging.info("Exiting...")
        player.stop_playback()


if __name__ == "__main__":
    main()

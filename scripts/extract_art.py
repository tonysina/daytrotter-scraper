#!/usr/bin/env python3
"""
Extract the embedded ID3 cover art from one track per session (a small
ranged HTTP fetch, not a full download), resize it small, and store it as
a base64 JPEG in sessions.db so the browser page can embed it as a data:
URI -- sidestepping the fact that the hosted page can't hotlink
img.pastemagazine.com directly.
"""
import io
import time
import base64
from urllib.request import Request, urlopen

from mutagen.id3 import ID3, ID3NoHeaderError
from PIL import Image, ImageFile

import _batch

DB_PATH = "data/sessions.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 daytrotter-archive-personal-use/1.0"
# Some files' embedded art is short a few bytes at the source; the missing
# pixels are invisible at thumbnail size, so decode what's there.
ImageFile.LOAD_TRUNCATED_IMAGES = True

RANGE_BYTES = 400_000
THUMB_SIZE = 96
JPEG_QUALITY = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS art (
    url TEXT PRIMARY KEY,     -- session url
    data_b64 TEXT,
    status TEXT,              -- ok | no_art | error
    fetched_at INTEGER
);
"""


def worker(item):
    session_url, track_url = item
    try:
        req = Request(track_url, headers={"User-Agent": UA, "Range": f"bytes=0-{RANGE_BYTES}"})
        with urlopen(req, timeout=20) as resp:
            raw = resp.read()
        try:
            apics = ID3(io.BytesIO(raw)).getall("APIC")
        except ID3NoHeaderError:  # raw MP3 frames, no tag: nothing to extract
            return "no_art", None
        if not apics:
            return "no_art", None
        img = Image.open(io.BytesIO(apics[0].data)).convert("RGB")
        img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return "ok", base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return "error", None


def save(conn, item, result):
    status, b64 = result
    conn.execute(
        "INSERT OR REPLACE INTO art (url, data_b64, status, fetched_at) VALUES (?,?,?,?)",
        (item[0], b64, status, int(time.time())),
    )


def main():
    ap = _batch.make_parser(default_workers=10)
    args = ap.parse_args()

    conn = _batch.connect(DB_PATH, SCHEMA)
    # One representative track per session: its first track with a URL.
    targets = conn.execute("""
        SELECT s.url, t.mp3_url FROM sessions s
        JOIN tracks t ON t.url = s.url AND t.mp3_url IS NOT NULL
        WHERE s.status = 'ok' AND t.track_number = (
            SELECT MIN(track_number) FROM tracks WHERE url = s.url AND mp3_url IS NOT NULL
        )
    """).fetchall()

    _batch.run(conn, "art", "url", targets, key_fn=lambda t: t[0], worker_fn=worker, save_fn=save,
               args=args, done_statuses=("ok", "no_art"))
    conn.close()


if __name__ == "__main__":
    main()

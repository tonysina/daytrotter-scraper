#!/usr/bin/env python3
"""
Scrape Daytrotter session pages hosted on pastemagazine.com.

Resumable: writes to a SQLite DB, skips URLs already fetched successfully.
Run repeatedly (e.g. via background loop) until complete.
"""
import re
import json
import time
from html import unescape
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import _batch

DB_PATH = "data/sessions.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) daytrotter-archive-personal-use/1.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    url TEXT PRIMARY KEY,
    artist TEXT,
    artist_slug TEXT,
    subtitle TEXT,
    date_raw TEXT,
    location TEXT,
    image_url TEXT,
    fetched_at INTEGER,
    status TEXT,      -- ok | error | no_tracks
    error TEXT
);
CREATE TABLE IF NOT EXISTS tracks (
    url TEXT,
    track_number INTEGER,
    title TEXT,
    mp3_url TEXT,
    PRIMARY KEY (url, track_number)
);
"""

H1_RE = re.compile(r'<h1 class="title">\s*<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', re.S)
H2_RE = re.compile(r'<h2 class="subtitle">([^<]*)</h2>')
LI_TRACK_RE = re.compile(r'<li class="grid-x"[^>]*data-track="[^"]*streamingUrl[^"]*"[^>]*>')
STREAM_URL_RE = re.compile(r'streamingUrl&quot;:&quot;([^&]+?)&quot;')
LI_TITLE_ATTR_RE = re.compile(r'\btitle="([^"]*)"')
LI_TITLE_INNER_RE = re.compile(r'<i class="ellipsis small-10">([^<]*)</i>')


def parse_page(url, html):
    row = {"url": url, "status": "ok", "error": None}

    m = H1_RE.search(html)
    row["artist_slug"] = m.group(1).strip() if m else None
    row["artist"] = unescape(m.group(2)).strip() if m else None

    m = H2_RE.search(html)
    subtitle = unescape(m.group(1)).strip() if m else None
    row["subtitle"] = subtitle

    location = None
    date_raw = subtitle
    if subtitle:
        # e.g. "Jan 29, 2014 Daytrotter Studio Rock Island, IL"
        # or   "Daytrotter Session  - May 28, 2026"
        loc_m = re.search(r'(Daytrotter Stud(?:io|ios)[^,]*,\s*[A-Za-z]+)', subtitle)
        if loc_m:
            location = loc_m.group(1).strip()
            date_raw = subtitle.replace(location, '').strip()
        date_raw = re.sub(r'^Daytrotter Session\s*-?\s*', '', date_raw).strip()
    row["location"] = location
    row["date_raw"] = date_raw

    img_m = re.search(r'<img src="(https://img\.pastemagazine\.com/[^"]+)" alt="', html)
    row["image_url"] = img_m.group(1) if img_m else None

    tracks = []
    for i, li in enumerate(LI_TRACK_RE.findall(html)):
        mp3_m = STREAM_URL_RE.search(li)
        if not mp3_m:
            continue
        title_m = LI_TITLE_ATTR_RE.search(li)
        title = title_m.group(1) if title_m else None
        if not title:
            inner_m = LI_TITLE_INNER_RE.search(li)
            title = inner_m.group(1) if inner_m else f"Track {i+1}"
        tracks.append((i, unescape(title).strip(), mp3_m.group(1).replace('\\/', '/')))

    if not tracks:
        # Fallback: older "recap" article template embeds a JSON blob instead
        # of the standard track-list widget (no direct mp3 URL available).
        embed_m = re.search(r"data-tracks='(\[[^']+\])'", html)
        if embed_m:
            try:
                data = json.loads(unescape(embed_m.group(1)))
                for i, t in enumerate(data):
                    tracks.append((i, t.get("Song") or f"Track {i+1}", None))
                if data and data[0].get("Artist") and not row["artist"]:
                    row["artist"] = data[0]["Artist"]
                if data and data[0].get("ShowDate") and not row["date_raw"]:
                    row["date_raw"] = data[0]["ShowDate"]
            except Exception:
                pass

    row["tracks"] = tracks
    if not tracks:
        row["status"] = "no_tracks"
    return row


def worker(url):
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        return parse_page(url, html)
    except (HTTPError, URLError, TimeoutError) as e:
        return {"url": url, "status": "error", "error": str(e), "tracks": [],
                "artist": None, "artist_slug": None, "subtitle": None, "date_raw": None,
                "location": None, "image_url": None}
    except Exception as e:
        return {"url": url, "status": "error", "error": f"parse:{e}", "tracks": [],
                "artist": None, "artist_slug": None, "subtitle": None, "date_raw": None,
                "location": None, "image_url": None}


def save(conn, url, row):
    conn.execute(
        "INSERT OR REPLACE INTO sessions (url, artist, artist_slug, subtitle, date_raw, location, image_url, fetched_at, status, error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (row["url"], row["artist"], row["artist_slug"], row["subtitle"], row["date_raw"],
         row["location"], row["image_url"], int(time.time()), row["status"], row.get("error")),
    )
    conn.execute("DELETE FROM tracks WHERE url=?", (url,))
    for tn, title, mp3 in row["tracks"]:
        conn.execute(
            "INSERT OR REPLACE INTO tracks (url, track_number, title, mp3_url) VALUES (?,?,?,?)",
            (url, tn, title, mp3),
        )


def main():
    ap = _batch.make_parser(default_workers=8)
    ap.add_argument("--urls-file", default="data/session_urls.txt")
    args = ap.parse_args()

    conn = _batch.connect(DB_PATH, SCHEMA)
    urls = [u.strip() for u in open(args.urls_file) if u.strip()]
    _batch.run(conn, "sessions", "url", urls, key_fn=lambda u: u, worker_fn=worker, save_fn=save,
               args=args, done_statuses=("ok", "no_tracks"))
    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Enrich each distinct Daytrotter session artist with genre/tag data from
MusicBrainz (https://musicbrainz.org/doc/MusicBrainz_API).

MusicBrainz's usage policy requires a descriptive User-Agent and no more
than 1 request/second, so this runs serially. Resumable via the 'artists' table.
"""
import json
import time
import urllib.parse
from urllib.request import Request, urlopen

import _batch

DB_PATH = "data/sessions.db"
UA = "daytrotter-personal-archive/1.0 ( https://github.com/tonysina/daytrotter-scraper )"
MB_URL = "https://musicbrainz.org/ws/2/artist/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS artists (
    artist TEXT PRIMARY KEY,
    mbid TEXT,
    genres TEXT,       -- JSON array of strings
    disambiguation TEXT,
    looked_up_at INTEGER,
    status TEXT         -- ok | not_found | error
);
"""


def extract_genres(artist_obj):
    tags = artist_obj.get("tags", []) or []
    genres = {g["name"] for g in (artist_obj.get("genres") or [])}
    # tags are folksonomy and noisier; only keep ones with at least one vote
    genres |= {t["name"] for t in tags if t.get("count", 0) >= 1}
    return sorted(genres)


def worker(name):
    try:
        q = urllib.parse.quote(f'artist:"{name}"')
        req = Request(f"{MB_URL}?query={q}&fmt=json&limit=1", headers={"User-Agent": UA})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        artists = data.get("artists", [])
        if not artists:
            return {"status": "not_found", "mbid": None, "genres": [], "disambiguation": None}
        best = artists[0]
        return {"status": "ok", "mbid": best.get("id"), "genres": extract_genres(best),
                "disambiguation": best.get("disambiguation")}
    except Exception:
        return {"status": "error", "mbid": None, "genres": None, "disambiguation": None}


def save(conn, name, r):
    conn.execute(
        "INSERT OR REPLACE INTO artists (artist, mbid, genres, disambiguation, looked_up_at, status) "
        "VALUES (?,?,?,?,?,?)",
        (name, r["mbid"], json.dumps(r["genres"]) if r["genres"] is not None else None,
         r["disambiguation"], int(time.time()), r["status"]),
    )


def main():
    args = _batch.make_parser().parse_args()

    conn = _batch.connect(DB_PATH, SCHEMA)
    artists = [r[0] for r in conn.execute(
        "SELECT DISTINCT artist FROM sessions WHERE status = 'ok' AND artist IS NOT NULL ORDER BY artist")]
    _batch.run(conn, "artists", "artist", artists, key_fn=lambda a: a, worker_fn=worker, save_fn=save,
               args=args, done_statuses=("ok", "not_found"), sleep_after=1.0)
    conn.close()


if __name__ == "__main__":
    main()

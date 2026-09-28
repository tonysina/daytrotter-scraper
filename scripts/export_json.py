#!/usr/bin/env python3
"""Export sessions.db for the browser page, in two forms, from one pass
over the data (no re-reading from disk between them):

  data/sessions.json + data/artists.json + data/images-manifest.json +
  data/images-N.json   - fetched at runtime by index.html when it's served
     (claude.ai Artifact or a local http server); art is chunked to stay
     under the 16MB-per-file cap a published Artifact enforces.

  "Daytrotter Archive.html" - index.html with all of the above baked in as
     inert JSON <script> blocks, so it needs no server at all: double-click
     and open. No cap to chunk against since it's just a local file.

De-dupes (artist, date_raw) pairs, keeping the row with more tracks.
"""
import json
import os
import re
import sqlite3

conn = sqlite3.connect("data/sessions.db")
conn.row_factory = sqlite3.Row

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_iso_date(date_raw):
    """Return 'YYYY.MM.DD' or None if unparseable."""
    if not date_raw:
        return None
    d = date_raw.strip()
    m = re.match(r'([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})', d)
    if m:
        mon = MONTHS.get(m.group(1)[:3].lower())
        if mon:
            return f"{int(m.group(3)):04d}.{mon:02d}.{int(m.group(2)):02d}"
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', d)
    if m:
        return f"{int(m.group(3)):04d}.{int(m.group(1)):02d}.{int(m.group(2)):02d}"
    return None


def year_of(date_raw, iso):
    if iso:
        return int(iso[:4])
    m = re.search(r'(19|20)\d{2}', date_raw or "")
    return int(m.group(0)) if m else None


rows = conn.execute("SELECT * FROM sessions WHERE status='ok' ORDER BY artist, date_raw").fetchall()
tracks_by_url = {}
for t in conn.execute("SELECT url, title, mp3_url FROM tracks ORDER BY url, track_number"):
    tracks_by_url.setdefault(t["url"], []).append((t["title"], t["mp3_url"]))

best = {}
for r in rows:
    key = (r["artist"], r["date_raw"])
    tracks = tracks_by_url.get(r["url"], [])
    if key not in best or len(tracks) > len(best[key][1]):
        best[key] = (r, tracks)

sessions = []
for (artist, date_raw), (r, tracks) in best.items():
    if not artist:
        continue
    iso = parse_iso_date(date_raw)
    sessions.append({
        "a": artist,
        "y": year_of(date_raw, iso),
        "d": date_raw,
        "iso": iso,
        "u": r["url"],
        "tr": [list(t) for t in tracks],
    })

sessions.sort(key=lambda s: (s["a"].lower(), s["y"] or 0))

artist_rows = conn.execute("SELECT artist, genres FROM artists WHERE status='ok'").fetchall()
artists = {r["artist"]: json.loads(r["genres"]) for r in artist_rows if json.loads(r["genres"] or "[]")}

with open("data/sessions.json", "w") as f:
    json.dump(sessions, f, separators=(",", ":"))
with open("data/artists.json", "w") as f:
    json.dump(artists, f, separators=(",", ":"))

# Cover art: extracted from each session's own ID3 tag (see extract_art.py),
# embedded as data: URIs so the sandboxed Artifact preview can render them
# without hotlinking img.pastemagazine.com (which it can't reach).
art_rows = conn.execute("SELECT url, data_b64 FROM art WHERE status='ok'").fetchall()
CHUNK_BUDGET = 14 * 1024 * 1024
chunks = []
current, current_size = {}, 0
for r in art_rows:
    uri = f"data:image/jpeg;base64,{r['data_b64']}"
    entry_size = len(r["url"]) + len(uri) + 8
    if current and current_size + entry_size > CHUNK_BUDGET:
        chunks.append(current)
        current, current_size = {}, 0
    current[r["url"]] = uri
    current_size += entry_size
if current:
    chunks.append(current)

for i, chunk in enumerate(chunks):
    with open(f"data/images-{i}.json", "w") as f:
        json.dump(chunk, f, separators=(",", ":"))
with open("data/images-manifest.json", "w") as f:
    json.dump({"chunks": len(chunks), "count": len(art_rows)}, f)

# Standalone build: same sessions/artists/art already computed above, no
# separate script re-reading them from disk or re-querying the DB.
art_all = {r["url"]: f"data:image/jpeg;base64,{r['data_b64']}" for r in art_rows}


def embed(id_, obj):
    # A title containing the literal string "</script" would otherwise
    # close this inert JSON block early.
    body = json.dumps(obj, separators=(",", ":")).replace("</script", "<\\/script")
    return f'<script type="application/json" id="{id_}">{body}</script>\n'


standalone = open("index.html").read()
data_scripts = embed("__DATA__", {"sessions": sessions, "artists": artists}) + embed("__ART__", art_all)
standalone = standalone.replace("<script>", data_scripts + "<script>", 1)
with open("Daytrotter Archive.html", "w") as f:
    f.write(standalone)

print(f"sessions: {len(sessions)}")
print(f"artists with genre data: {len(artists)}")
print(f"iso date coverage: {sum(1 for s in sessions if s['iso'])}/{len(sessions)}")
print(f"cover art: {len(art_rows)} images in {len(chunks)} chunk file(s)")
years = [s["y"] for s in sessions if s["y"]]
print("year range:", min(years), "-", max(years))
print(f'standalone: "Daytrotter Archive.html" ({os.path.getsize("Daytrotter Archive.html")/1024/1024:.1f} MB)')

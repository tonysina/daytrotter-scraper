# daytrotter-scraper

A personal archive tool for [Daytrotter](https://en.wikipedia.org/wiki/Daytrotter) sessions — because the real archive is ten times bigger than the website lets you see, and I wanted to actually browse it.

## What Daytrotter even is

Starting in 2006 out of a barn in Rock Island, Illinois, Daytrotter talked touring bands into stopping by and recording a handful of songs live, no overdubs, straight to tape. Over the next decade-plus it became one of the great quiet institutions of indie music — thousands of sessions from everyone between total unknowns and Bon Iver, Alabama Shakes, The National, all free to stream and download. The studio moved to Davenport, Iowa at some point. The site eventually got folded into Paste Magazine. The original daytrotter.com now just 301-redirects to Paste's homepage, like nothing ever happened there.

## The problem this solves

Paste's own `/daytrotter` hub page shows you a "New" feed and a "Best of" list — maybe 115 sessions total. That's it. That's the whole front door.

But it turns out the actual archive is still fully alive underneath, just completely unlinked from anywhere a human would find it. I went digging through Paste's WordPress sitemap and found **7,274 real sessions** going back to 2006, hiding behind URLs nobody links to. There's also a `tag` taxonomy in that sitemap — `daytrotter-studio-rock-island-il`, `daytrotter-studios-davenport-ia` — that looks like it should let you browse by recording location, except every single one of those tag pages 302-redirects to the homepage. Whoever migrated this content to WordPress broke the archive browsing on the way in and nobody ever went back to fix it.

So: a scraper, a local database, and a browser page that actually lets you search, filter, and listen to the thing that's already sitting there.

## The fun part: where the cover art actually lives

Every session page on Paste shows a hand-drawn portrait of the artist — kraft-paper card, black ink linework, a little decorative scalloped frame corner, the whole recognizable Daytrotter look. Those images are hosted on `img.pastemagazine.com`, and it turns out you *can't* reliably fetch them from a script or a sandboxed page — CDN quirks, hotlink protection, take your pick.

Except the exact same portrait is also embedded as ID3 cover art inside every single track's MP3 file. So instead of touching the image CDN at all, this scraper sends a small **ranged HTTP request** (the first ~400KB of a track, not the whole file) to each session's first song, pulls the `APIC` frame out of the ID3 tag with `mutagen`, and resizes it down with Pillow. No full downloads needed just to get a thumbnail — the album art was hiding in the audio the whole time.

## What's actually in here

| | |
|---|---|
| Sessions | 7,274 |
| Artists | 5,767 |
| Tracks | ~35,600 |
| Years covered | 2006–2026 |
| Cover art recovered from ID3 tags | ~6,500 sessions |
| Genre tags | pulled from [MusicBrainz](https://musicbrainz.org), rate-limited to their 1 req/sec policy |

## The pipeline

Five small scripts, each one resumable (safe to kill and rerun — they pick up where they left off):

```
scripts/discover_urls.py     crawls Paste's sitemap for every session URL (the site's own hub page won't show you these)
scripts/scrape_sessions.py   scrapes each session page (artist, date, tracklist, mp3 URLs)
scripts/extract_art.py       ranged-fetches one track per session, pulls the ID3 cover art
scripts/enrich_genres.py     looks up each artist's genre tags on MusicBrainz (1 req/sec, be polite)
scripts/export_json.py       builds the standalone HTML page, with everything embedded
scripts/_batch.py            shared plumbing the three scrapers above all use
```

Everything lands in one SQLite database (`data/sessions.db`) so you can poke at it directly if you want.

### Setup

```bash
pip install mutagen Pillow
```

(Everything else — `urllib`, `sqlite3`, `concurrent.futures` — is standard library. No scraping framework, no ORM, no build step.)

### Running it

```bash
# 1. Find every session URL via Paste's sitemap:
python3 scripts/discover_urls.py

# 2. Scrape each one (artist, date, tracklist, mp3 URLs):
python3 scripts/scrape_sessions.py --workers 10

# 3. Pull cover art out of the MP3s:
python3 scripts/extract_art.py --workers 10

# 4. Tag genres via MusicBrainz (slow on purpose — 1/sec):
python3 scripts/enrich_genres.py

# 5. Export everything, including the finished standalone page:
python3 scripts/export_json.py
```

Steps 2-4 all take `--limit N` (process a handful first, to make sure it's working) and `--retry-errors` (re-attempt anything that failed last time). Kill any of them with Ctrl-C and rerun later — they resume from where they left off instead of starting over.

Step 5 produces **`Daytrotter Archive.html`** — one self-contained file with all the data baked directly into it. Double-click it. No server, no terminal, nothing to run. Browse by artist (with a proper A-Z index that knows "The Antlers" files under A, not T), filter by genre, expand a session to see the tracklist and real cover art, click a track to download it with a sane filename (`Daytrotter - Artist - YYYY.MM.DD - Track.mp3`), or grab a whole session as a zip in one click.

## Why it's a `.html` file and not a website

Because the moment you make it a server-hosted thing, you inherit a server: uptime, hosting, "why is this down," all of it for a tool that exactly one person uses. A single static file that opens directly in a browser has none of those problems and never will.

The one trick worth knowing: browsers refuse to `fetch()` local files from a `file://` page, which is normally *the* reason people reach for `python -m http.server`. The workaround here is to skip fetching local files entirely — the session data and every thumbnail are embedded straight into the HTML as inert `<script type="application/json">` blocks, parsed with `JSON.parse()` on load. The only network calls left at runtime are to the actual audio host for downloads, which is a perfectly normal cross-origin request with permissive CORS headers, not a security boundary browsers care about.

## A note on scope

This is scraping one person's (mine) way through a public archive for personal listening, not a redistribution project — the repo ships the *code*, not the scraped data or the ~6,500 recovered cover images. If you want your own copy of the archive, run the pipeline yourself; be a reasonable citizen about request rates while you do (the defaults already are).

## License

Do whatever you want with the code. The music and the artist portraits belong to Daytrotter, Paste Magazine, and the artists — this is just a better set of eyes on an archive they already made public.

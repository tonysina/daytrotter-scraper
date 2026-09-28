#!/usr/bin/env python3
"""
Find every Daytrotter session URL by crawling Paste's WordPress sitemap
(robots.txt points at /wp-sitemap.xml) -- Paste's own /daytrotter hub page
only lists a curated ~115 sessions, but the sitemap indexes all of them.

Writes data/session_urls.txt, one URL per line, for scrape_sessions.py to use.
"""
import re
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 daytrotter-archive-personal-use/1.0"
SITEMAP_INDEX = "https://www.pastemagazine.com/wp-sitemap.xml"

# Paste's sitemap also lists non-session Daytrotter content (brand history,
# app announcements, recap articles that embed a different, non-scrapable
# track widget) -- these substrings identify pages worth keeping vs skipping.
KEEP_IF = re.compile(r'daytrotter-session|daytrotter-studio', re.I)
SKIP_IF = re.compile(
    r'watch-and-listen|hear-|on-this-day|announcing|paste-music-daytrotter-app|'
    r'daytrotter-beer|logos|portrait-of-daytrotter-artist|comedy|/design/|/drink/',
    re.I,
)


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main():
    index = fetch(SITEMAP_INDEX)
    article_sitemaps = re.findall(r'<loc>(https://www\.pastemagazine\.com/wp-sitemap-posts-article-\d+\.xml)</loc>', index)
    print(f"found {len(article_sitemaps)} article sitemap files")

    urls = set()
    for i, sitemap_url in enumerate(article_sitemaps, 1):
        for url in re.findall(r'<loc>([^<]+)</loc>', fetch(sitemap_url)):
            if "daytrotter" in url.lower():
                urls.add(url)
        if i % 10 == 0:
            print(f"  scanned {i}/{len(article_sitemaps)} sitemap files, {len(urls)} daytrotter urls so far")

    sessions = sorted(u for u in urls if KEEP_IF.search(u) and not SKIP_IF.search(u))
    print(f"{len(urls)} daytrotter-related urls -> {len(sessions)} look like real sessions")

    with open("data/session_urls.txt", "w") as f:
        f.write("\n".join(sessions) + "\n")
    print("wrote data/session_urls.txt")


if __name__ == "__main__":
    main()

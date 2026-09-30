from html.parser import HTMLParser
from html import escape
from email.utils import formatdate
from urllib.parse import urlparse
from pathlib import Path
import time

INPUT_FILE = Path("index.html")
OUTPUT_FILE = Path("feed.xml")

SITE_URL = "https://trendradar-3d0.pages.dev/"
FEED_URL = "https://trendradar-3d0.pages.dev/feed.xml"


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            if href.startswith("http://") or href.startswith("https://"):
                self.current_href = href
                self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current_href:
            title = " ".join("".join(self.current_text).split())
            if title:
                self.links.append((title, self.current_href))
            self.current_href = None
            self.current_text = []


def is_valid_news_link(title, url):
    if len(title) < 5:
        return False

    domain = urlparse(url).netloc.lower()

    excluded_domains = [
        "trendradar-3d0.pages.dev",
        "github.com",
        "cloudflare.com",
    ]

    if any(d in domain for d in excluded_domains):
        return False

    excluded_titles = [
        "github",
        "导出",
        "展开",
        "收起",
        "trendradar",
    ]

    lowered = title.lower()

    if any(word in lowered for word in excluded_titles):
        return False

    return True


if not INPUT_FILE.exists():
    raise SystemExit("index.html 不存在，无法生成 RSS")

html = INPUT_FILE.read_text(encoding="utf-8")

parser = LinkExtractor()
parser.feed(html)

items = []
seen = set()

for title, url in parser.links:
    if not is_valid_news_link(title, url):
        continue

    key = (title, url)

    if key in seen:
        continue

    seen.add(key)
    items.append((title, url))

items = items[:150]

now = formatdate(time.time(), usegmt=True)

rss_items = []

for title, url in items:
    rss_items.append(
        f"""
    <item>
      <title>{escape(title)}</title>
      <link>{escape(url)}</link>
      <guid isPermaLink="true">{escape(url)}</guid>
      <pubDate>{now}</pubDate>
      <description>{escape(title)}</description>
    </item>
"""
    )

rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>TrendRadar 热点新闻分析</title>
    <link>{SITE_URL}</link>
    <description>TrendRadar 筛选整理后的热点新闻</description>
    <language>zh-cn</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link xmlns:atom="http://www.w3.org/2005/Atom"
              href="{FEED_URL}"
              rel="self"
              type="application/rss+xml" />

{''.join(rss_items)}

  </channel>
</rss>
"""

OUTPUT_FILE.write_text(rss, encoding="utf-8")

print(f"✅ feed.xml 已生成，共 {len(items)} 条内容")

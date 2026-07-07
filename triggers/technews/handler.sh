#!/bin/bash
set -u

FEED_URL="${TECHNEWS_RSS_URL:-https://karaage0703.github.io/tech-blog-rss-feed/feeds/rss.xml}"
LIMIT="${TECHNEWS_LIMIT:-5}"

curl -s --max-time 15 "$FEED_URL" 2>/dev/null | \
  python3 -c "
import sys, xml.etree.ElementTree as ET
limit = int('${LIMIT}')
tree = ET.parse(sys.stdin)
items = tree.findall('.//item')[:limit]
for item in items:
    title = item.find('title').text if item.find('title') is not None else ''
    link = item.find('link').text if item.find('link') is not None else ''
    print(f'- {title}\n  {link}\n')
" 2>/dev/null || echo "ニュースの取得に失敗しました"

#!/bin/bash
curl -s "https://karaage0703.github.io/tech-blog-rss-feed/feeds/rss.xml" 2>/dev/null | \
  uv run --python 3.12 python -c "
import sys, xml.etree.ElementTree as ET
tree = ET.parse(sys.stdin)
items = tree.findall('.//item')[:5]
for item in items:
    title = item.find('title').text if item.find('title') is not None else ''
    link = item.find('link').text if item.find('link') is not None else ''
    print(f'- {title}\n  {link}\n')
" 2>/dev/null || echo "ニュースの取得に失敗しました"

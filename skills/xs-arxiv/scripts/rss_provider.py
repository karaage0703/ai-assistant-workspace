"""
arXiv 公式 RSS フィードから新着論文を取得する provider。

rss.arxiv.org は export.arxiv.org/api/query と違いレート制限ほぼ無し。
カテゴリ別フィードを並列取得して、過去 N 日の新着を返す。

毎朝の cron トレンド用途に最適。任意クエリ検索は不可 (それは s2_provider で)。
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

RSS_BASE = "https://rss.arxiv.org/rss/"
DEFAULT_CATEGORIES = ("cs.AI", "cs.LG", "cs.CL", "cs.CV")
USER_AGENT = "arxiv-skill-fetcher/1.0 (https://github.com/karaage0703/ai-assistant-workspace)"
REQUEST_TIMEOUT_SEC = 20


_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def _extract_arxiv_id(entry) -> Optional[str]:
    """RSS entry から arxiv ID (e.g. 2401.12345v1) を抽出"""
    # rss.arxiv.org の id フィールドは "oai:arXiv.org:2401.12345v1" 形式
    raw_id = entry.get("id", "")
    m = _ID_RE.search(raw_id)
    if m:
        return m.group(1) + (m.group(2) or "")
    # フォールバック: link から
    link = entry.get("link", "")
    m = _ID_RE.search(link)
    if m:
        return m.group(1) + (m.group(2) or "")
    return None


def _split_author_string(s: str) -> list[str]:
    """'A, B, C and D' -> ['A', 'B', 'C', 'D']"""
    # 'and' を ',' に揃えてから分割
    cleaned = re.sub(r"\s+and\s+", ", ", s)
    return [name.strip() for name in cleaned.split(",") if name.strip()]


def _parse_authors(entry) -> list[str]:
    # rss.arxiv.org は authors として [{"name": "A, B, C and D"}] という 1 要素リストを返すことがある
    if "authors" in entry and isinstance(entry["authors"], list):
        raw_names: list[str] = []
        for a in entry["authors"]:
            if isinstance(a, dict):
                n = a.get("name")
                if n:
                    raw_names.append(n)
            elif isinstance(a, str):
                raw_names.append(a)
        if raw_names:
            # 1 要素にカンマ区切りでまとめられているケースをさらに分割
            expanded: list[str] = []
            for n in raw_names:
                if "," in n or " and " in n:
                    expanded.extend(_split_author_string(n))
                else:
                    expanded.append(n.strip())
            return expanded
    if "author" in entry:
        return _split_author_string(entry["author"])
    return []


_ABSTRACT_PREFIX_RE = re.compile(
    r"^\s*arXiv:\s*\d{4}\.\d{4,5}(v\d+)?\s*Announce Type:[^\n]*\n+\s*Abstract:\s*",
    re.IGNORECASE,
)


def _parse_categories(entry) -> list[str]:
    cats = []
    if "tags" in entry:
        for t in entry["tags"]:
            term = t.get("term") if isinstance(t, dict) else getattr(t, "term", None)
            if term:
                cats.append(term)
    return cats


def _parse_published(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        tt = entry.get(key)
        if tt:
            try:
                return datetime(*tt[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _fetch_one_category(category: str) -> tuple[str, list[dict], Optional[str]]:
    """1 カテゴリの RSS を取得。返り値: (category, papers, error_or_None)"""
    url = f"{RSS_BASE}{category}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return category, [], f"{exc.__class__.__name__}: {exc}"

    feed = feedparser.parse(resp.content)
    papers = []
    for entry in feed.entries:
        arxiv_id = _extract_arxiv_id(entry)
        if not arxiv_id:
            continue
        published = _parse_published(entry)
        # rss.arxiv.org の summary は "arXiv:ID Announce Type: ... \nAbstract: 本文" 形式
        abstract = entry.get("summary", "").strip()
        abstract = _ABSTRACT_PREFIX_RE.sub("", abstract).strip()
        abstract = re.sub(r"^Abstract:\s*", "", abstract).strip()
        papers.append(
            {
                "id": arxiv_id,
                "title": entry.get("title", "").strip(),
                "authors": _parse_authors(entry),
                "abstract": abstract,
                "categories": _parse_categories(entry) or [category],
                "published": published.isoformat() if published else "",
                "url": f"https://arxiv.org/pdf/{arxiv_id}",
                "arxiv_url": f"http://arxiv.org/abs/{arxiv_id}",
                "source_category": category,
            }
        )
    return category, papers, None


def fetch_trending(
    categories: Optional[list[str]] = None,
    days: int = 7,
    max_results: int = 20,
) -> dict:
    """
    指定カテゴリの RSS を並列取得して、過去 `days` 日の新着論文を返す。

    Returns:
        {"total_results": N, "papers": [...], "categories_queried": [...],
         "categories_failed": [{"category": ..., "error": ...}, ...],
         "source": "rss"}
    """
    cats = list(categories) if categories else list(DEFAULT_CATEGORIES)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    all_papers: dict[str, dict] = {}  # arxiv_id -> paper (dedup across categories)
    failed: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(len(cats), 6)) as executor:
        futures = {executor.submit(_fetch_one_category, c): c for c in cats}
        for fut in as_completed(futures):
            cat, papers, err = fut.result()
            if err:
                failed.append({"category": cat, "error": err})
                continue
            for p in papers:
                pub = p.get("published")
                if pub:
                    try:
                        pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass
                pid = p["id"].split("v")[0]  # v1/v2 を同一視
                # 同じ arxiv_id を複数カテゴリで拾った場合は categories をマージ
                if pid in all_papers:
                    existing = all_papers[pid]
                    merged = set(existing.get("categories", [])) | set(p.get("categories", []))
                    existing["categories"] = sorted(merged)
                else:
                    all_papers[pid] = p

    # published が新しい順にソート
    sorted_papers = sorted(
        all_papers.values(),
        key=lambda x: x.get("published", ""),
        reverse=True,
    )[:max_results]

    return {
        "total_results": len(sorted_papers),
        "papers": sorted_papers,
        "categories_queried": cats,
        "categories_failed": failed,
        "source": "rss",
        "days": days,
    }

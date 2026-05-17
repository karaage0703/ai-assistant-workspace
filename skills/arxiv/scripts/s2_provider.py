"""
Semantic Scholar Graph API を使った任意クエリ論文検索。

export.arxiv.org/api/query と違い、レート制限が緩く (匿名でも 100 req/5min)、
arxiv ID で個別取得・abstract / 著者 / 公開日 / OA PDF URL がリッチに取れる。

Docs: https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = ",".join(
    [
        "paperId",
        "externalIds",
        "title",
        "abstract",
        "authors.name",
        "year",
        "publicationDate",
        "venue",
        "fieldsOfStudy",
        "openAccessPdf",
        "citationCount",
        "influentialCitationCount",
    ]
)
USER_AGENT = "arxiv-skill-fetcher/1.0 (https://github.com/karaage0703/ai-assistant-workspace)"
REQUEST_TIMEOUT_SEC = 30

# 失敗時の外側リトライ (Semantic Scholar も 429 を返すことはある)
OUTER_RETRY_DELAYS_SEC = (5, 15, 30)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _request_with_retry(url: str, params: dict) -> tuple[Optional[dict], Optional[str]]:
    """GET with exponential backoff. 戻り値: (json_or_None, error_or_None)"""
    last_err: Optional[str] = None
    for attempt_idx in range(len(OUTER_RETRY_DELAYS_SEC) + 1):
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SEC,
            )
        except Exception as exc:  # noqa: BLE001
            last_err = f"{exc.__class__.__name__}: {exc}"
            if attempt_idx >= len(OUTER_RETRY_DELAYS_SEC):
                break
            sleep_sec = OUTER_RETRY_DELAYS_SEC[attempt_idx] + random.uniform(0, 3)
            logger.warning("S2 network error (try %d): %s, sleeping %.1fs", attempt_idx + 1, last_err, sleep_sec)
            time.sleep(sleep_sec)
            continue

        if resp.status_code == 200:
            try:
                return resp.json(), None
            except Exception as exc:  # noqa: BLE001
                return None, f"JSON decode error: {exc}"

        if resp.status_code in RETRYABLE_STATUS:
            last_err = f"HTTP {resp.status_code}"
            if attempt_idx >= len(OUTER_RETRY_DELAYS_SEC):
                break
            sleep_sec = OUTER_RETRY_DELAYS_SEC[attempt_idx] + random.uniform(0, 3)
            logger.warning("S2 retryable error (try %d): HTTP %d, sleeping %.1fs",
                           attempt_idx + 1, resp.status_code, sleep_sec)
            time.sleep(sleep_sec)
            continue

        # 非リトライ系 (404 など)
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"

    return None, last_err or "unknown error"


def _normalize_paper(s2_paper: dict) -> dict:
    """S2 paper JSON を arxiv_fetcher と互換のフォーマットに変換"""
    ext = s2_paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv") or ext.get("arxiv") or ""

    oa = s2_paper.get("openAccessPdf") or {}
    pdf_url = oa.get("url") or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "")

    authors = [a.get("name", "") for a in (s2_paper.get("authors") or []) if a.get("name")]

    pub_date = s2_paper.get("publicationDate") or ""
    if not pub_date and s2_paper.get("year"):
        pub_date = f"{s2_paper['year']}-01-01"

    return {
        "id": arxiv_id,
        "title": s2_paper.get("title", "").strip(),
        "authors": authors,
        "abstract": (s2_paper.get("abstract") or "").strip(),
        "categories": s2_paper.get("fieldsOfStudy") or [],
        "published": pub_date,
        "url": pdf_url,
        "arxiv_url": f"http://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
        "citation_count": s2_paper.get("citationCount"),
        "influential_citation_count": s2_paper.get("influentialCitationCount"),
        "venue": s2_paper.get("venue"),
        "s2_paper_id": s2_paper.get("paperId"),
    }


def search(query: str, max_results: int = 10, year_from: Optional[int] = None) -> dict:
    """
    Semantic Scholar で任意クエリ検索。arxiv ID を持つ論文のみ返す。

    max_results は S2 では最大 100 までで指定可。
    """
    params = {
        "query": query,
        "limit": min(max(max_results * 2, 10), 100),  # arxiv フィルタで減るので多めに
        "fields": DEFAULT_FIELDS,
    }
    if year_from:
        params["year"] = f"{year_from}-"

    data, err = _request_with_retry(f"{S2_BASE}/paper/search", params)
    if err:
        return {
            "error": "Semantic Scholar search failed",
            "detail": err,
            "retries_exhausted": True,
            "hint": "数分待ってから再試行、または APIキー登録で制限緩和を検討",
            "source": "s2",
        }

    papers = []
    for p in (data.get("data") or []):
        ext = p.get("externalIds") or {}
        if not (ext.get("ArXiv") or ext.get("arxiv")):
            continue  # arxiv にない論文は除外
        papers.append(_normalize_paper(p))
        if len(papers) >= max_results:
            break

    return {
        "total_results": len(papers),
        "papers": papers,
        "source": "s2",
        "query": query,
    }


def get_by_arxiv_id(arxiv_id: str) -> dict:
    """arxiv ID 1 件を S2 で取得 (metadata 補完用)"""
    # S2 は "ARXIV:2401.12345" 形式を受け付ける (v1 は付けない)
    clean_id = arxiv_id.split("v")[0]
    data, err = _request_with_retry(
        f"{S2_BASE}/paper/ARXIV:{clean_id}",
        {"fields": DEFAULT_FIELDS},
    )
    if err:
        return {"error": "Semantic Scholar lookup failed", "detail": err, "arxiv_id": arxiv_id, "source": "s2"}
    return {"paper": _normalize_paper(data), "source": "s2"}

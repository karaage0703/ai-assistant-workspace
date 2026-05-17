"""
arXiv論文取得モジュール
"""

import json
import logging
import random
import time
from datetime import timezone
from pathlib import Path
from typing import Optional

import arxiv
from arxiv import HTTPError, UnexpectedEmptyPageError
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# arxiv API レート制限対策のチューニング値
#  - delay_seconds: arxiv 公式推奨は 3 秒。混雑時間帯（6:30 JST = 21:30 UTC）で
#    弾かれにくいよう 5 秒に余裕を持たせる
#  - num_retries: ライブラリ内部リトライを 3 → 5 に増やす
#  - page_size: 通常用途では 20 件取れれば十分なので小さくして 1 ページで完結
ARXIV_CLIENT_KWARGS = dict(page_size=20, delay_seconds=5.0, num_retries=5)

# search/download 全体を包む外側リトライ（指数バックオフ + jitter）
OUTER_RETRY_DELAYS_SEC = (15, 45, 90)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _build_client() -> arxiv.Client:
    return arxiv.Client(**ARXIV_CLIENT_KWARGS)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.status in RETRYABLE_STATUS
    if isinstance(exc, UnexpectedEmptyPageError):
        return True
    # ConnectionError 等のネット系も再試行対象
    return exc.__class__.__name__ in {"ConnectionError", "ChunkedEncodingError", "ReadTimeout", "Timeout"}


def _retry_describe(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.status}"
    return f"{exc.__class__.__name__}: {exc}"

# 有効なarXivカテゴリプレフィックス
VALID_CATEGORIES = {
    "cs",
    "econ",
    "eess",
    "math",
    "physics",
    "q-bio",
    "q-fin",
    "stat",
    "astro-ph",
    "cond-mat",
    "gr-qc",
    "hep-ex",
    "hep-lat",
    "hep-ph",
    "hep-th",
    "math-ph",
    "nlin",
    "nucl-ex",
    "nucl-th",
    "quant-ph",
}


def validate_categories(categories: list[str]) -> bool:
    """カテゴリの妥当性を検証"""
    for category in categories:
        prefix = category.split(".")[0] if "." in category else category
        if prefix not in VALID_CATEGORIES:
            return False
    return True


def process_paper(paper: arxiv.Result) -> dict:
    """論文情報を辞書形式に変換"""
    return {
        "id": paper.get_short_id(),
        "title": paper.title,
        "authors": [author.name for author in paper.authors],
        "abstract": paper.summary,
        "categories": paper.categories,
        "published": paper.published.isoformat(),
        "url": paper.pdf_url,
        "arxiv_url": paper.entry_id,
    }


def search_papers(
    query: str,
    max_results: int = 10,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    categories: Optional[list[str]] = None,
    sort_by: str = "relevance",
) -> dict:
    """arXiv論文を検索"""
    # クエリ構築
    query_parts = [f"({query})"]

    # カテゴリフィルタ
    if categories:
        if not validate_categories(categories):
            return {"error": "Invalid category provided"}
        category_filter = " OR ".join(f"cat:{cat}" for cat in categories)
        query_parts.append(f"({category_filter})")

    final_query = " ".join(query_parts)

    # ソート方法
    sort_criterion = arxiv.SortCriterion.SubmittedDate if sort_by == "date" else arxiv.SortCriterion.Relevance

    search = arxiv.Search(
        query=final_query,
        max_results=max_results + 5,  # 日付フィルタ用に余分に取得
        sort_by=sort_criterion,
    )

    # 日付フィルタのパース
    date_from_parsed = None
    date_to_parsed = None
    if date_from:
        date_from_parsed = date_parser.parse(date_from).replace(tzinfo=timezone.utc)
    if date_to:
        date_to_parsed = date_parser.parse(date_to).replace(tzinfo=timezone.utc)

    attempts: list[str] = []
    last_exc: Optional[Exception] = None
    for attempt_idx in range(len(OUTER_RETRY_DELAYS_SEC) + 1):
        client = _build_client()
        try:
            results = []
            for paper in client.results(search):
                if len(results) >= max_results:
                    break

                paper_date = paper.published
                if not paper_date.tzinfo:
                    paper_date = paper_date.replace(tzinfo=timezone.utc)

                if date_from_parsed and paper_date < date_from_parsed:
                    continue
                if date_to_parsed and paper_date > date_to_parsed:
                    continue

                results.append(process_paper(paper))

            return {"total_results": len(results), "papers": results, "attempts": attempt_idx + 1}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            attempts.append(_retry_describe(exc))
            if not _is_retryable(exc) or attempt_idx >= len(OUTER_RETRY_DELAYS_SEC):
                break
            sleep_sec = OUTER_RETRY_DELAYS_SEC[attempt_idx] + random.uniform(0, 5)
            logger.warning(
                "arxiv search retryable error (try %d/%d): %s — sleeping %.1fs",
                attempt_idx + 1,
                len(OUTER_RETRY_DELAYS_SEC) + 1,
                _retry_describe(exc),
                sleep_sec,
            )
            time.sleep(sleep_sec)

    return {
        "error": "arxiv API request failed after retries",
        "detail": _retry_describe(last_exc) if last_exc else "unknown",
        "attempts": attempts,
        "retries_exhausted": True,
        "hint": "2分以上待ってから --date-from を狭めて (例: 過去3日)、または -n を小さくして再実行",
    }


def download_paper(paper_id: str, output_dir: str = "./papers", convert_to_md: bool = True) -> dict:
    """論文をダウンロードしてMarkdownに変換"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    md_path = output_path / f"{paper_id.replace('/', '_')}.md"
    pdf_path = output_path / f"{paper_id.replace('/', '_')}.pdf"

    # 既にMarkdownが存在する場合
    if md_path.exists():
        return {
            "status": "success",
            "message": "Paper already available",
            "path": str(md_path),
        }

    try:
        # 取得は外側リトライでラップ（download_pdf 自体は内部リトライ無し）
        paper = None
        last_exc: Optional[Exception] = None
        for attempt_idx in range(len(OUTER_RETRY_DELAYS_SEC) + 1):
            client = _build_client()
            try:
                paper = next(client.results(arxiv.Search(id_list=[paper_id])))
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_retryable(exc) or attempt_idx >= len(OUTER_RETRY_DELAYS_SEC):
                    raise
                sleep_sec = OUTER_RETRY_DELAYS_SEC[attempt_idx] + random.uniform(0, 5)
                logger.warning(
                    "arxiv download metadata retryable error (try %d): %s — sleeping %.1fs",
                    attempt_idx + 1,
                    _retry_describe(exc),
                    sleep_sec,
                )
                time.sleep(sleep_sec)
        assert paper is not None

        # PDFダウンロード
        paper.download_pdf(dirpath=str(output_path), filename=pdf_path.name)

        if convert_to_md:
            try:
                import pymupdf4llm

                markdown = pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)

                # メタデータを先頭に追加
                metadata = f"""---
title: "{paper.title}"
authors: {json.dumps([a.name for a in paper.authors])}
published: {paper.published.isoformat()}
arxiv_id: {paper_id}
categories: {json.dumps(paper.categories)}
url: {paper.entry_id}
---

# {paper.title}

**Authors**: {", ".join(a.name for a in paper.authors)}

**Published**: {paper.published.strftime("%Y-%m-%d")}

**arXiv**: [{paper_id}]({paper.entry_id})

**Abstract**: {paper.summary}

---

"""
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(metadata + markdown)

                # PDFを削除
                pdf_path.unlink(missing_ok=True)

                return {
                    "status": "success",
                    "message": "Paper downloaded and converted to Markdown",
                    "path": str(md_path),
                    "title": paper.title,
                }
            except ImportError:
                return {
                    "status": "partial",
                    "message": "PDF downloaded but pymupdf4llm not installed for conversion",
                    "path": str(pdf_path),
                }
        else:
            return {
                "status": "success",
                "message": "PDF downloaded",
                "path": str(pdf_path),
            }

    except StopIteration:
        return {"status": "error", "message": f"Paper {paper_id} not found on arXiv"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_papers(output_dir: str = "./papers") -> dict:
    """ダウンロード済み論文の一覧を取得"""
    output_path = Path(output_dir)

    if not output_path.exists():
        return {"total": 0, "papers": []}

    papers = []
    for md_file in output_path.glob("*.md"):
        paper_id = md_file.stem
        # フロントマターからタイトルを抽出
        title = None
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read(1000)  # 最初の1000文字だけ読む
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        frontmatter = content[3:end]
                        for line in frontmatter.split("\n"):
                            if line.startswith("title:"):
                                title = line[6:].strip().strip('"')
                                break
        except Exception:
            pass

        papers.append(
            {
                "id": paper_id,
                "title": title,
                "path": str(md_file),
            }
        )

    return {"total": len(papers), "papers": papers}


def read_paper(paper_id: str, output_dir: str = "./papers") -> dict:
    """論文の内容を読み込み"""
    md_path = Path(output_dir) / f"{paper_id.replace('/', '_')}.md"

    if not md_path.exists():
        return {"status": "error", "message": f"Paper {paper_id} not found. Download it first."}

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "paper_id": paper_id, "content": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

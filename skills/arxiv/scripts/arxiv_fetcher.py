"""
arXiv論文取得モジュール
"""

import json
from datetime import timezone
from pathlib import Path
from typing import Optional

import arxiv
from dateutil import parser as date_parser

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
    client = arxiv.Client()

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

    # 結果処理
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

    return {"total_results": len(results), "papers": results}


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
        client = arxiv.Client()
        paper = next(client.results(arxiv.Search(id_list=[paper_id])))

        # PDFダウンロード
        paper.download_pdf(dirpath=str(output_path), filename=pdf_path.name)

        if convert_to_md:
            try:
                from markitdown import MarkItDown

                mid = MarkItDown()
                result_md = mid.convert(str(pdf_path))
                markdown = result_md.text_content

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
                    "message": "PDF downloaded but markitdown not installed for conversion",
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

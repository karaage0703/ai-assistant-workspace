#!/usr/bin/env python3
"""
arXiv論文検索・ダウンロード・変換CLIツール

使用例:
    # 検索
    uv run python arxiv_tool.py search "transformer attention" -n 10 -c cs.AI cs.LG

    # ダウンロード（Markdown変換付き）
    uv run python arxiv_tool.py download 2401.12345 -o ./papers

    # 論文一覧
    uv run python arxiv_tool.py list -o ./papers

    # 論文読み込み
    uv run python arxiv_tool.py read 2401.12345 -o ./papers

    # LaTeXソース取得（数式が多い論文向け）
    uv run python arxiv_tool.py latex 2401.12345
    uv run python arxiv_tool.py latex 2401.12345 --abstract-only
    uv run python arxiv_tool.py latex 2401.12345 --sections
    uv run python arxiv_tool.py latex 2401.12345 --section "2.1"

LaTeXソース取得機能は arxiv-to-prompt (MIT License, (c) 2025 Takashi Ishida) を使用。
https://github.com/takashiishida/arxiv-to-prompt
"""

import argparse
import json
import sys

from arxiv_fetcher import (
    search_papers,
    download_paper,
    list_papers,
    read_paper,
)


def main():
    parser = argparse.ArgumentParser(description="arXiv論文検索・ダウンロードツール")
    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # search コマンド
    search_parser = subparsers.add_parser("search", help="論文を検索")
    search_parser.add_argument("query", help="検索クエリ")
    search_parser.add_argument("-n", "--max-results", type=int, default=10, help="最大結果数")
    search_parser.add_argument("--date-from", help="開始日 (YYYY-MM-DD)")
    search_parser.add_argument("--date-to", help="終了日 (YYYY-MM-DD)")
    search_parser.add_argument("-c", "--categories", nargs="+", help="カテゴリ (例: cs.AI cs.LG)")
    search_parser.add_argument("-s", "--sort-by", choices=["relevance", "date"], default="relevance", help="ソート方法")

    # download コマンド
    download_parser = subparsers.add_parser("download", help="論文をダウンロード")
    download_parser.add_argument("paper_id", help="arXiv論文ID (例: 2401.12345)")
    download_parser.add_argument("-o", "--output-dir", default="./papers", help="出力ディレクトリ")
    download_parser.add_argument("--pdf-only", action="store_true", help="PDFのみ（Markdown変換しない）")

    # list コマンド
    list_parser = subparsers.add_parser("list", help="ダウンロード済み論文一覧")
    list_parser.add_argument("-o", "--output-dir", default="./papers", help="論文ディレクトリ")

    # read コマンド
    read_parser = subparsers.add_parser("read", help="論文を読み込み")
    read_parser.add_argument("paper_id", help="arXiv論文ID")
    read_parser.add_argument("-o", "--output-dir", default="./papers", help="論文ディレクトリ")

    # latex コマンド
    latex_parser = subparsers.add_parser("latex", help="LaTeXソースを取得（数式が多い論文向け）")
    latex_parser.add_argument("paper_id", help="arXiv論文ID (例: 2401.12345)")
    latex_parser.add_argument("--abstract-only", action="store_true", help="アブストラクトのみ取得")
    latex_parser.add_argument("--sections", action="store_true", help="セクション一覧を表示")
    latex_parser.add_argument("--section", help="特定セクションを取得 (例: 1, 2.1, Introduction)")

    args = parser.parse_args()

    if args.command == "search":
        result = search_papers(
            query=args.query,
            max_results=args.max_results,
            date_from=args.date_from,
            date_to=args.date_to,
            categories=args.categories,
            sort_by=args.sort_by,
        )
    elif args.command == "download":
        result = download_paper(
            paper_id=args.paper_id,
            output_dir=args.output_dir,
            convert_to_md=not args.pdf_only,
        )
    elif args.command == "list":
        result = list_papers(output_dir=args.output_dir)
    elif args.command == "read":
        result = read_paper(paper_id=args.paper_id, output_dir=args.output_dir)
    elif args.command == "latex":
        try:
            from arxiv_to_prompt import process_latex_source, list_sections, extract_section
        except ImportError:
            print(json.dumps({"error": "arxiv-to-prompt がインストールされていません。uv sync を実行してください。"}, ensure_ascii=False))
            sys.exit(1)

        try:
            if args.abstract_only:
                text = process_latex_source(args.paper_id, abstract_only=True)
                result = {"paper_id": args.paper_id, "type": "abstract", "content": text}
            elif args.sections:
                text = process_latex_source(args.paper_id)
                sections = list_sections(text)
                result = {"paper_id": args.paper_id, "type": "sections", "sections": sections}
            elif args.section:
                text = process_latex_source(args.paper_id)
                section_text = extract_section(text, args.section)
                if section_text is None:
                    result = {"paper_id": args.paper_id, "error": f"セクション '{args.section}' が見つかりません。--sections で一覧を確認してください。"}
                else:
                    result = {"paper_id": args.paper_id, "type": "section", "section_path": args.section, "content": section_text}
            else:
                text = process_latex_source(args.paper_id)
                result = {"paper_id": args.paper_id, "type": "full_latex", "content": text}
        except Exception as e:
            result = {"paper_id": args.paper_id, "error": str(e)}
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

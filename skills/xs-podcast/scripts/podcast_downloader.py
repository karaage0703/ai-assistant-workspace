#!/usr/bin/env python3
"""
汎用ポッドキャスト音声ダウンローダー
RSS フィードから音声ファイルをダウンロードする汎用ツール
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests


class PodcastDownloader:
    def __init__(self, output_dir="podcast_audio"):
        self.output_dir = output_dir
        self.session = requests.Session()

    def get_rss_from_itunes_id(self, itunes_id):
        """iTunes IDからRSSフィードURLを取得"""
        try:
            url = f"https://itunes.apple.com/lookup?id={itunes_id}"
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get("results"):
                return data["results"][0].get("feedUrl")
            return None
        except Exception as e:
            print(f"iTunes API エラー: {e}")
            return None

    def get_rss_feed(self, rss_url):
        """RSSフィードを取得"""
        try:
            print(f"RSSフィード取得中: {rss_url}")
            response = self.session.get(rss_url)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"RSSフィード取得エラー: {e}")
            return None

    def parse_rss(self, rss_content):
        """RSSフィードを解析してエピソード情報を抽出"""
        try:
            root = ET.fromstring(rss_content)
            episodes = []

            # ポッドキャスト情報を取得
            channel = root.find(".//channel")
            podcast_title = "Unknown Podcast"
            if channel is not None:
                title_elem = channel.find("title")
                if title_elem is not None:
                    podcast_title = title_elem.text

            for item in root.findall(".//item"):
                title = item.find("title")
                title_text = title.text if title is not None else "不明なタイトル"

                pub_date = item.find("pubDate")
                pub_date_text = pub_date.text if pub_date is not None else "不明な日付"

                description = item.find("description")
                description_text = description.text if description is not None else ""

                # 音声ファイルURLを取得 (複数の方法で試行)
                audio_url = None

                # 1. enclosure タグから取得
                enclosure = item.find("enclosure")
                if enclosure is not None and enclosure.get("type", "").startswith("audio"):
                    audio_url = enclosure.get("url")

                # 2. media:content タグから取得
                if not audio_url:
                    for media_content in item.findall(".//{http://search.yahoo.com/mrss/}content"):
                        if media_content.get("type", "").startswith("audio"):
                            audio_url = media_content.get("url")
                            break

                # 3. link タグから取得
                if not audio_url:
                    link = item.find("link")
                    if link is not None and link.text:
                        url = link.text
                        if any(ext in url.lower() for ext in [".mp3", ".m4a", ".wav", ".ogg"]):
                            audio_url = url

                if audio_url:
                    episodes.append(
                        {
                            "title": title_text,
                            "pub_date": pub_date_text,
                            "description": description_text,
                            "audio_url": audio_url,
                            "podcast_title": podcast_title,
                        }
                    )

            return episodes, podcast_title
        except ET.ParseError as e:
            print(f"RSS解析エラー: {e}")
            return [], "Unknown Podcast"

    def sanitize_filename(self, filename):
        """ファイル名を安全な形式に変換"""
        # 不正な文字を除去・置換
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
        filename = re.sub(r"\s+", " ", filename).strip()
        return filename[:200]

    def get_file_extension(self, url):
        """URLから拡張子を推定"""
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower()

        # よくある音声拡張子
        if ext in [".mp3", ".m4a", ".wav", ".ogg", ".aac"]:
            return ext

        # デフォルトは mp3
        return ".mp3"

    def download_audio(self, episode, filename, podcast_dir):
        """音声ファイルをダウンロード"""
        filepath = os.path.join(podcast_dir, filename)

        # ファイルが既に存在する場合はスキップ
        if os.path.exists(filepath):
            print(f"スキップ: {filename} (既に存在)")
            return True

        try:
            print(f"ダウンロード中: {filename}")
            response = self.session.get(episode["audio_url"], stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded_size = 0

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)

                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            print(f"\r進捗: {progress:.1f}%", end="", flush=True)

            print(f"\n完了: {filename}")
            return True

        except requests.RequestException as e:
            print(f"\nダウンロードエラー: {filename} - {e}")
            return False

    def save_episode_info(self, episodes, podcast_dir):
        """エピソード情報をJSONファイルに保存"""
        info_file = os.path.join(podcast_dir, "episode_info.json")
        episode_info = []

        for i, episode in enumerate(episodes):
            episode_info.append(
                {
                    "index": i + 1,
                    "title": episode["title"],
                    "pub_date": episode["pub_date"],
                    "description": episode["description"][:500],  # 説明文は500文字まで
                    "audio_url": episode["audio_url"],
                }
            )

        with open(info_file, "w", encoding="utf-8") as f:
            json.dump(episode_info, f, ensure_ascii=False, indent=2)

        print(f"エピソード情報を保存: {info_file}")

    def show_episode_list(self, episodes, max_episodes=None):
        """エピソード一覧を表示"""
        display_episodes = episodes[:max_episodes] if max_episodes else episodes

        for i, episode in enumerate(display_episodes):
            title = episode["title"]
            pub_date = episode["pub_date"]
            description = episode.get("description", "").strip()

            # 概要を整理 - HTMLタグを除去し、先頭200文字に制限
            if description:
                # HTMLタグの簡易除去
                import re

                description = re.sub(r"<[^>]+>", "", description)
                description = description.replace("\n", " ").replace("\r", "")
                description = " ".join(description.split())  # 複数の空白を1つに

                # 長すぎる場合は切り詰め
                if len(description) > 200:
                    description = description[:200] + "..."

                concept = description if description else "概要なし"
            else:
                concept = "概要なし"

            print(f"{i + 1}. {title}")
            print(f"   公開日: {pub_date}")
            print(f"   概要: {concept}")
            print()

    def get_episode_list(self, rss_url=None, itunes_id=None, max_episodes=None):
        """エピソード一覧のみを取得・表示"""
        # RSSフィードURLを取得
        if itunes_id:
            rss_url = self.get_rss_from_itunes_id(itunes_id)
            if not rss_url:
                print(f"iTunes ID {itunes_id} からRSSフィードを取得できませんでした")
                return False

        if not rss_url:
            print("RSSフィードURLまたはiTunes IDが必要です")
            return False

        # RSSフィードを取得・解析
        rss_content = self.get_rss_feed(rss_url)
        if not rss_content:
            return False

        episodes, detected_podcast_title = self.parse_rss(rss_content)
        if not episodes:
            print("エピソード情報を取得できませんでした")
            return False

        print(f"ポッドキャスト: {detected_podcast_title}")
        print(f"総エピソード数: {len(episodes)}")
        print()

        # エピソード一覧を表示
        self.show_episode_list(episodes, max_episodes)
        return True

    def download_podcast(self, rss_url=None, itunes_id=None, max_episodes=None, podcast_name=None):
        """ポッドキャストをダウンロード"""

        # RSSフィードURLを取得
        if itunes_id:
            rss_url = self.get_rss_from_itunes_id(itunes_id)
            if not rss_url:
                print(f"iTunes ID {itunes_id} からRSSフィードを取得できませんでした")
                return False

        if not rss_url:
            print("RSSフィードURLまたはiTunes IDが必要です")
            return False

        # RSSフィードを取得・解析
        rss_content = self.get_rss_feed(rss_url)
        if not rss_content:
            return False

        episodes, detected_podcast_title = self.parse_rss(rss_content)
        if not episodes:
            print("エピソード情報を取得できませんでした")
            return False

        # ポッドキャスト名を決定
        final_podcast_name = podcast_name or self.sanitize_filename(detected_podcast_title)
        podcast_dir = os.path.join(self.output_dir, final_podcast_name)

        if not os.path.exists(podcast_dir):
            os.makedirs(podcast_dir)

        print(f"ポッドキャスト: {detected_podcast_title}")
        print(f"取得したエピソード数: {len(episodes)}")
        print(f"保存先: {podcast_dir}")

        # ダウンロード数を制限
        download_episodes = episodes[:max_episodes] if max_episodes else episodes
        print(f"ダウンロード予定: {len(download_episodes)} エピソード")

        # エピソード情報を保存
        self.save_episode_info(download_episodes, podcast_dir)

        # 音声ファイルをダウンロード
        success_count = 0
        for i, episode in enumerate(download_episodes):
            print(f"\n[{i + 1}/{len(download_episodes)}] {episode['title']}")

            # ファイル名を生成
            extension = self.get_file_extension(episode["audio_url"])
            filename = f"{i + 1:03d}_{self.sanitize_filename(episode['title'])}{extension}"

            if self.download_audio(episode, filename, podcast_dir):
                success_count += 1

        print(f"\n完了: {success_count}/{len(download_episodes)} エピソードをダウンロードしました")
        return success_count > 0


def main():
    parser = argparse.ArgumentParser(description="汎用ポッドキャスト音声ダウンローダー")
    parser.add_argument("-r", "--rss", help="RSSフィードURL")
    parser.add_argument("-i", "--itunes-id", help="iTunes ID")
    parser.add_argument("-n", "--max-episodes", type=int, help="最大ダウンロード数")
    parser.add_argument("-o", "--output", default="podcast_audio", help="出力ディレクトリ")
    parser.add_argument("-p", "--podcast-name", help="ポッドキャスト名 (ディレクトリ名)")
    parser.add_argument("-l", "--list-only", action="store_true", help="エピソード一覧のみ表示（ダウンロードしない）")

    args = parser.parse_args()

    if not args.rss and not args.itunes_id:
        print("使用例:")
        print("  RSSフィードから: python podcast_downloader.py -r 'https://example.com/feed.rss'")
        print("  iTunes IDから: python podcast_downloader.py -i 1450522865")
        print("  最大5エピソード: python podcast_downloader.py -r 'https://example.com/feed.rss' -n 5")
        print("  エピソード一覧のみ: python podcast_downloader.py -i 1450522865 -n 10 -l")
        sys.exit(1)

    downloader = PodcastDownloader(args.output)

    if args.list_only:
        success = downloader.get_episode_list(rss_url=args.rss, itunes_id=args.itunes_id, max_episodes=args.max_episodes)
    else:
        success = downloader.download_podcast(
            rss_url=args.rss, itunes_id=args.itunes_id, max_episodes=args.max_episodes, podcast_name=args.podcast_name
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

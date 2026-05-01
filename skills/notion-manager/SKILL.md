---
name: xs:notion-manager
description: Notion APIでページ検索・閲覧・作成、ファイルアップロード、画像付き日記作成、個別ブロックの更新・削除を行うスキル。「Notionで検索して」「Notionに日記書いて」「Notionにファイルアップロードして」「Notionの個別ブロックを修正して」で使用。
---

# Notion Manager

Notion APIを使ってページの検索・閲覧・作成、ファイルアップロードを行う。

## 絶対遵守事項

- APIキー設定が必要（初回のみ）
- 対象ページには「接続」許可が必要
- アップロードは20MB以下

## セットアップ（初回のみ）

1. https://notion.so/my-integrations でIntegration作成
2. APIキー（`ntn_xxx`）をコピー
3. 設定:
   ```bash
   mkdir -p ~/.config/notion
   echo "ntn_xxxxx" > ~/.config/notion/api_key
   ```
4. 対象ページで「...」→「接続」→ Integration名を選択

## コマンド一覧

### 検索
```bash
cd [WORKSPACE]/skills/notion-manager
uv run python notion_tool.py search "検索ワード"
uv run python notion_tool.py search "検索ワード" -t page  # ページのみ
uv run python notion_tool.py search "検索ワード" --json   # JSON出力
```

### ページ読み込み
```bash
uv run python notion_tool.py read <page_id>
uv run python notion_tool.py read <page_id> --json
uv run python notion_tool.py read <page_id> --with-ids  # 各ブロックIDを表示（編集対象を特定するため）
```

### ページ作成
```bash
uv run python notion_tool.py create <parent_id> "タイトル"
uv run python notion_tool.py create <parent_id> "タイトル" -c "本文"
uv run python notion_tool.py create <db_id> "タイトル" --database  # DB内に作成
```

### ファイルアップロード
```bash
# 画像をアップロード（imageブロックとして追加）
uv run python notion_tool.py upload photo.jpg <page_id>

# 動画をアップロード（videoブロックとして追加）
uv run python notion_tool.py upload video.mp4 <page_id>

# ファイルをアップロード（fileブロックとして追加）
uv run python notion_tool.py upload document.pptx <page_id> --as-file

# キャプション付き
uv run python notion_tool.py upload photo.jpg <page_id> -c "東京の風景"
```

**対応形式：**
- 画像: jpg, jpeg, png, gif, webp
- 動画: mp4, mov, webm, avi, mkv
- その他: pdf, pptx, docx, xlsx

### 個別ブロックの取得・更新・削除

```bash
# 1. ブロックIDを調べる（read --with-ids でページ内の全ブロックIDを表示）
uv run python notion_tool.py read <page_id> --with-ids

# 2. 単一ブロックの取得
uv run python notion_tool.py get-block <block_id>
uv run python notion_tool.py get-block <block_id> --json

# 3. ブロックのテキスト更新（既存タイプを維持）
uv run python notion_tool.py update <block_id> -t "新しいテキスト"

# 4. リンク付きテキストに変更
uv run python notion_tool.py update <block_id> -t "クリックでサイトへ" --link "https://example.com"

# 5. To-doブロックのチェック切替
uv run python notion_tool.py update <block_id> --checked
uv run python notion_tool.py update <block_id> --unchecked

# 6. ブロックタイプを切り替え（段落 ↔ 見出し ↔ 箇条書き等）
uv run python notion_tool.py update <block_id> --type bulleted_list_item    # 段落→箇条書き
uv run python notion_tool.py update <block_id> -l 3                         # 見出し2 → 見出し3
uv run python notion_tool.py update <block_id> --type heading_2 -t "新タイトル"  # テキストも同時変更

# 7. ブロック削除（-y で確認スキップ）
uv run python notion_tool.py delete <block_id> -y
```

**対応ブロックタイプ:** paragraph, heading_1〜3, bulleted_list_item, numbered_list_item, to_do, quote, code

**注意:**
- Notion API はブロックタイプの直接変更を許可しないため、`--type` 指定時は **新タイプを直後に挿入 → 旧ブロック削除** で位置を保ちつつ置き換える（新ブロックIDが返る）
- `--type` の対応タイプ: paragraph / heading_1〜3 / bulleted_list_item / numbered_list_item / to_do / quote
- 画像・動画・ファイルブロックは `update` 非対応 → `delete` して `upload` で再投稿
- `delete` は archive 扱い（Notion上はゴミ箱に入る、復元可）

### ページに追記（append）
```bash
# 見出し追加
uv run python notion_tool.py append <page_id> -H "セクション名" -l 2

# テキスト追加
uv run python notion_tool.py append <page_id> -t "本文テキスト"

# 箇条書き追加
uv run python notion_tool.py append <page_id> -b "箇条書きアイテム"

# クリッカブルなリンク付き箇条書き
uv run python notion_tool.py append <page_id> -b "リンクテキスト" --link "https://example.com"

# 複数の箇条書き
uv run python notion_tool.py append <page_id> --bullets "項目1" "項目2" "項目3"
```

### 添付ファイルのダウンロード

`read --json` で取得した JSON の `file` ブロックには署名付きURLが入る。`curl -sL -o <out> <url>` でダウンロード。**URLは1時間で期限切れ**なので取得後すぐに。

### 日記作成（画像付き）
```bash
# シンプルな日記
uv run python notion_tool.py diary <parent_page_id>

# タイトル・内容・画像付き
uv run python notion_tool.py diary <parent_page_id> \
  -t "2026-01-30 日記" \
  -c "今日の出来事" \
  -i photo1.jpg photo2.jpg
```

## Page IDの取得方法

NotionのページURL末尾の32文字（ハイフンなし）がPage ID。
`https://notion.so/Page-Title-abc123def456...` の `abc123def456...` 部分。

---

制限事項・トラブルシューティングは [`README.md`](./README.md) を参照。

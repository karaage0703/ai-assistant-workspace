---
name: xs:notion-manager
description: Notion APIでページ検索・閲覧・作成、ファイルアップロード、画像付き日記作成を行うスキル。「Notionで検索して」「Notionに日記書いて」「Notionにファイルアップロードして」で使用。
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

Notionページに添付されたファイル（PDF等）をダウンロードする手順：

```bash
# 1. JSON出力でファイルブロックの署名付きURLを取得
cd [WORKSPACE]/skills/notion-manager
uv run python notion_tool.py read <page_id> --json 2>/dev/null > /tmp/notion_output.json

# 2. fileブロックからURLを抽出
python3 -c "
import json
with open('/tmp/notion_output.json') as f:
    data = json.load(f)
for b in data.get('results', []):
    if b.get('type') == 'file':
        url = b['file']['file']['url']
        name = b['file'].get('name', 'unknown')
        print(f'{name}: {url}')
"

# 3. curlでダウンロード
curl -sL -o /tmp/<filename> "<上記で取得したURL>"
```

**注意:** 署名付きURLは1時間で期限切れになるため、取得後すぐにダウンロードすること。

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

## 対話フロー

### Notion検索

**ユーザー:** 「Notionで〇〇を検索して」

```bash
cd [WORKSPACE]/skills/notion-manager
uv run python notion_tool.py search "〇〇"
```

### 画像付き日記

**ユーザー:** 「今日の写真をNotionに日記として記録して」

1. 画像ファイルのパスを確認
2. 日記用親ページIDを確認
3. 実行:
   ```bash
   uv run python notion_tool.py diary <parent_id> \
     -t "2026-01-30 日記" \
     -c "今日の出来事" \
     -i /path/to/photo.jpg
   ```

### 資料アップロード

**ユーザー:** 「このスライドをNotionにアップロードして」

```bash
uv run python notion_tool.py upload presentation.pptx <page_id> --as-file
```

## Page IDの取得方法

1. NotionでページをWebブラウザで開く
2. URLの末尾の32文字がPage ID
   ```
   https://notion.so/Page-Title-abc123def456...
                                  ^^^^^^^^^^^^ これ
   ```

## 制限事項

- ファイルサイズ: 20MB以下
- 対応形式: jpg, png, gif, webp, pdf, pptx, docx, xlsx 等
- APIキー未設定だとエラー
- 接続許可のないページにはアクセス不可

## トラブルシューティング

### "unauthorized" エラー
→ APIキーが正しいか確認、ページに「接続」許可したか確認

### "object_not_found" エラー
→ Page IDが正しいか確認、接続許可があるか確認

### ファイルアップロード失敗
→ 20MB以下か確認、対応形式か確認

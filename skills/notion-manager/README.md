# notion-manager

Notion API をCLIから叩くスキル。詳細手順は [`SKILL.md`](./SKILL.md)。

## できること

- 検索（`search`）— ページ・データベース横断
- ページ読み込み（`read`、`--with-ids` でブロックID表示）
- ページ作成（`create`、DB内・通常ページ両対応）
- ファイルアップロード（`upload`、画像/動画/PDF/Office等）
- ページ追記（`append`、見出し/段落/箇条書き/リンク付き）
- 日記作成（`diary`、画像複数枚＋日付プロパティ、重複画像スキップ）
- 個別ブロック編集
  - `get-block` — 単一ブロック取得
  - `update` — テキスト・リンク・to-doチェック切替（同タイプ内）
  - `update --type` / `-l` — タイプ変換（段落↔見出し↔箇条書き等）
  - `delete` — ブロック削除（archive扱い）

## 構成

| ファイル | 役割 |
|---------|------|
| `SKILL.md` | 使い方・コマンドリファレンス |
| `notion_tool.py` | CLI 実装本体（requests ベース） |
| `pyproject.toml` / `uv.lock` | uv で管理する依存（`requests` のみ） |

## 実行例

```bash
cd [WORKSPACE]/skills/notion-manager
uv run python notion_tool.py --help
```

## セットアップ

`~/.config/notion/api_key` に Integration の API キーを保存し、対象ページに「接続」許可を付ける。詳細は SKILL.md の「セットアップ（初回のみ）」を参照。

## 制限事項

- ファイルサイズ: 20MB以下
- APIキー未設定だとエラー
- 接続許可のないページにはアクセス不可

## トラブルシューティング

| エラー | 対処 |
|--------|------|
| `unauthorized` | APIキーが正しいか／ページに「接続」したか確認 |
| `object_not_found` | Page ID と接続許可を確認 |
| アップロード失敗 | 20MB以下／対応形式か確認 |

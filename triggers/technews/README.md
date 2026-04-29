# technews trigger

最新のテックニュースを取得して上位5件を返す `technews` トリガー。LLMが「最近のテックニュース教えて」のような発話に反応して呼び出す。

## ソース

[karaage0703/tech-blog-rss-feed](https://karaage0703.github.io/tech-blog-rss-feed/) のRSSフィード（日本のテックブログ・企業ブログを横断的にまとめたもの）から取得。

## 使用例

LLM経由（チャット）：

```
ユーザー: 最近のテックニュースある？
LLM: （内部で technews() を呼ぶ）
LLM: いま話題になってる記事は5本あるよ。1つ目は…
```

シェルから直叩き（デバッグ用）：

```bash
$ bash triggers/technews/handler.sh
- 最新のLLMトレンドについて
  https://example.com/article1
- Rustで作るCLIツール
  https://example.com/article2
...
```

## カスタマイズ

別のRSSフィードを使いたい場合は、`handler.sh` の `curl` 先URLを差し替えればOK。

```bash
curl -s "https://your.feed.example/rss.xml" 2>/dev/null | ...
```

複数フィードを横断したい・要約も付けたい場合は、トリガーよりも [`skills/tech-news-curation/`](../../skills/tech-news-curation/) スキルの方が向いている（AIが内容を見て選別・解説してくれる）。

## 違い: trigger vs. skill

| | `technews`（trigger） | `tech-news-curation`（skill） |
|---|---|---|
| 取得元 | 単一RSSフィード | 複数のRSS+条件付きキュレーション |
| 出力 | タイトルとURLのみ | 要約・選別理由付き |
| 速度 | 速い（1秒以内） | 遅い（モデル推論あり） |
| 用途 | サッと最新を流し見 | じっくり読みたいニュースを選別 |

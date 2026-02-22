---
name: podcast
description: ポッドキャストの音声取得・文字起こし・まとめを行う統合スキル。「ポッドキャストまとめて」「音声配信をダウンロード」「Podcastの内容を教えて」で使用。
---

# ポッドキャスト

ポッドキャストの音声取得から文字起こし・まとめまでを一貫して行う。

## できること

1. **音声ダウンロード** — iTunes ID/RSSからエピソードを取得
2. **文字起こし** — ダウンロードした音声をテキスト化
3. **まとめ作成** — 要約・キーポイント・詳細メモを生成

## 手順

### Step 1: 番組・エピソード確認

「どのポッドキャストをまとめますか？」

プリセット番組（番組名を言うだけでOK）：

- **からあげ帝国放送局** — iTunes ID: 1522851508 / LISTEN: https://listen.style/p/karaage0703
- **コテンラジオ** — iTunes ID: 1450522865 / LISTEN: https://listen.style/p/cotenradio
- **Rebuild** — iTunes ID: 603013428
- **ものづくりnoラジオ** — iTunes ID: 1646913578 / LISTEN: https://listen.style/p/sibucho_labo
- **fukabori.fm** — iTunes ID: 1388826609
- **サイエントーク** — iTunes ID: 1566371326 / LISTEN: https://listen.style/p/scientalk

上記以外の番組はiTunes IDまたはRSS URLを指定してもらう。

確認する情報：
- 番組名またはiTunes ID
- エピソード番号/タイトル

### Step 2: 取得手段の選択

| 手段 | 特徴 | 所要時間 |
|------|------|----------|
| 🥇 LISTEN | 文字起こし済み、高品質 | 数秒 |
| 🥈 YouTube字幕 | 動画版がある場合 | 数秒 |
| 🥉 音声DL→文字起こし | 確実だが時間かかる | 数分〜 |

**おすすめ:** LISTENで公開されていればLISTENを使う

### Step 3A: LISTENから取得する場合

```bash
# LISTENページから文字起こしを取得
# web_fetch https://listen.style/p/[番組]/[エピソードID]
```

### Step 3B: 音声をダウンロードする場合

```bash
# 番組の最新エピソードを確認
cd skills/podcast/scripts && uv run python podcast_downloader.py -i [iTunes_ID] -n 10 -l

# ダウンロード実行
cd skills/podcast/scripts && uv run python podcast_downloader.py -i [iTunes_ID] -n [エピソード数]
```

**iTunes IDの調べ方:**
Apple Podcastで番組ページを開き、URLの `id` 以降の数字がiTunes ID。
例: `https://podcasts.apple.com/jp/podcast/id1234567890` → iTunes ID は `1234567890`

### Step 4: 文字起こし（音声DLの場合）

`transcriber` スキルを使用：
```bash
uvx transcriber_tool transcribe "[音声ファイル]" --model-size base --output "[出力ファイル].txt"
```

### Step 5: まとめ作成

文字起こしから以下を作成：

```markdown
# [番組名] #[回] [タイトル]

**配信日:** YYYY/MM/DD
**長さ:** XX:XX

## 要約
（3-5行で内容を要約）

## キーポイント
- ポイント1
- ポイント2
- ポイント3

## 詳細メモ
（重要な発言や情報を箇条書き）

## 関連リンク
（番組内で紹介されたリンクがあれば）
```

### Step 6: 完了報告

まとめをチャットに提示して完了。

## 出力先

ダウンロードした音声：
```
skills/podcast/scripts/podcast_audio/
└── [番組名]/
    ├── 001_エピソード.mp3
    └── episode_info.json
```

## 使用例

```
「Rebuildの最新回をまとめて」
「○○ポッドキャストをダウンロードして文字起こしして」
「Podcastの内容を教えて」
```

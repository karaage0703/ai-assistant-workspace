---
name: youtube-notes
description: YouTube動画のURLから字幕を取得し、内容をノートにまとめる。「YouTube動画をまとめて」「この動画をノートにして」と言われたら使う。
---

# YouTube動画ノート化

YouTube動画から字幕を取得し、構造化されたノートを作成する。

## 手順

### Step 1: URLを受け取る

ユーザーからYouTube URLを受け取る。

### Step 2: 動画情報を取得

```bash
# 動画メタデータ取得
yt-dlp -J "[YouTube URL]"
```

### Step 3: 字幕を取得

```bash
# VIDEO_IDはURLから抽出（v=以降、またはyoutu.be/以降）
youtube_transcript_api [VIDEO_ID] --languages ja en --format text
```

### Step 4: ノートを作成

以下のフォーマットでノートを作成：

```markdown
# [動画タイトル]

## 基本情報
- **URL:** [YouTube URL]
- **時間:** XX分XX秒
- **チャンネル:** [チャンネル名]

## 概要
動画の内容を3-5行で要約

## 内容

### [セクション1]（0:00〜）
- ポイント1
- ポイント2

### [セクション2]（5:00〜）
- ポイント1
- ポイント2

## 重要ポイント
- 学び1
- 学び2
- 学び3

## 用語解説
- **用語1:** 説明
- **用語2:** 説明
```

### Step 5: 完了報告

ノート内容をチャットに表示する。

## 字幕がない場合

1. 音声を抽出
   ```bash
   yt-dlp -x --audio-format mp3 -o "audio.mp3" "[YouTube URL]"
   ```

2. `transcriber` スキルで文字起こし

## カスタマイズ

### 詳細度を変える

- 「簡潔にまとめて」→ 概要と重要ポイントのみ
- 「詳しくまとめて」→ 用語解説付きの詳細ノート

### 保存先を指定

「notes/に保存して」と言えば、ファイルとして保存される。

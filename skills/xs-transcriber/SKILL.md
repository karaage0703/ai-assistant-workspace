---
name: xs-transcriber
description: 音声ファイルをテキストに文字起こしするスキル。mp3/wav/m4a/ogg/flac形式に対応。whisperベースのtranscriber_toolを使用し、tiny/base/small/medium/largeの5つのモデルから精度と速度のバランスを選択可能。長時間音声はバックグラウンド実行に対応。「文字起こしして」「音声をテキストに変換して」で使用。
---

# 音声文字起こし

音声ファイルをテキストに変換する。

## 絶対遵守事項

- **長時間処理（10分以上の音声）はPID・ログ・終了コードを保存し、親process groupから分離して実行**

## 対話フロー

### Step 1: ファイル指定

**「文字起こしする音声ファイルのパスを指定してください」**

対応形式: mp3, wav, m4a, ogg, flac

### Step 2: モデル選択

**「文字起こしモデルを選択してください」**

| # | モデル | 速度 | 精度 | 用途 |
|---|--------|------|------|------|
| 1 | tiny | 最高速 | 最低 | テスト用 |
| 2 | base | 高速 | 標準 | **推奨** |
| 3 | small | 中速 | 中精度 | バランス |
| 4 | medium | 低速 | 高精度 | 高品質 |
| 5 | large | 最低速 | 最高 | 最高品質 |

### Step 3: 実行

出力先は音声ファイルと同じディレクトリに `.txt` 拡張子で保存。

```bash
# 短い音声（10分以下）はフォアグラウンド
uvx transcriber_tool transcribe "[音声ファイルパス]" --model-size [モデル] --output "[出力パス].txt"

# 長い音声（10分以上）はバックグラウンド
# 以下はLinux / WSLの例。macOSではlaunchdなどservice managerを使う
TRANSCRIPTION_STATE_DIR="$(mktemp -d)"
setsid bash -lc '
  state_dir="$1"
  input="$2"
  model="$3"
  output="$4"
  echo $$ > "$state_dir/pid"
  uvx transcriber_tool transcribe "$input" --model-size "$model" --output "$output" > "$state_dir/transcription.log" 2>&1
  rc=$?
  echo "$rc" > "$state_dir/exit"
  exit "$rc"
' bash "$TRANSCRIPTION_STATE_DIR" "[音声ファイルパス]" "[モデル]" "[出力パス].txt" >/dev/null 2>&1 &

sleep 2
ps -o pid,ppid,sid,pgid,stat,etime,cmd -p "$(cat "$TRANSCRIPTION_STATE_DIR/pid")"
echo "State: $TRANSCRIPTION_STATE_DIR"
```

### Step 4: 進行状況確認（バックグラウンド実行時）

```bash
# ログ確認
tail -f "$TRANSCRIPTION_STATE_DIR/transcription.log"

# 完了確認
cat "$TRANSCRIPTION_STATE_DIR/exit"
```

xangiでturnを跨ぐ場合は、処理の末尾で終了状態を保存した後に `xangi tool trigger` を呼ぶ。triggerを設定できない環境では、ログ・終了状態の確認をユーザーへ明示的に引き継ぎ、自動で戻ると約束しない。

### Step 5: 完了報告

文字起こし完了後、以下を報告:
- 出力ファイルパス
- 文字数（概算）
- 処理時間

## 処理時間目安

| 音声長 | tiny | base | medium | large |
|--------|------|------|--------|-------|
| 10分 | 30秒 | 1分 | 2-3分 | 5分 |
| 30分 | 1-2分 | 2-3分 | 5-8分 | 10-15分 |
| 60分 | 2-3分 | 4-6分 | 10-15分 | 20-30分 |

## トラブルシューティング

- **transcriber_tool未インストール**: 初回実行時に自動インストールされる
- **タイムアウト**: `setsid` で分離し、PID・ログ・終了コードを保存する
- **メモリ不足**: より小さいモデル（tiny/base）を使用
- **日本語の精度が低い**: モデルを large にする

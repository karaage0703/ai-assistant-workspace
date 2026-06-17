# モード D: スタックチャン連動（上級者向け）

> **対象**: モード A/B/C のいずれかで xangi が動いている人 / 物理アバターと連動させたい人
> **所要時間**: 約 60〜90 分（ハード入手済み・ファーム焼き含む）
> **前提**: モード A/B/C のどれかで xangi が動作中、対応 M5Stack ハード、USB 接続、PlatformIO

xangi の応答ライフサイクル（`turn.started` / `message.delta` / `turn.complete` / `agent.error`）を SSE 購読して、スタックチャン（M5Stack 製の卓上ロボット）に喋らせ・表情変更・首振りさせる連動構成。

公開リポ: <https://github.com/karaage0703/xangi-stackchan>（v0.2.0+、MIT）

## アーキテクチャ

```
xangi (port 18888)
  ↓ GET /api/events/stream (SSE)
xangi-stackchan bridge (PC 常駐、TTS = piper-plus or VOICEVOX)
  ↓ USB シリアル (WAV / FACE / MOVE / CAPTURE プロトコル)
M5Stack ファーム
```

## Step 1: ハードウェアを選ぶ

| デバイス | ファーム | baud | 機能 |
|---------|---------|------|------|
| K151 / K151-R（CoreS3 + サーボ + Remote） | `XangiBridge` | 921600 | WAV / FACE / MOVE（首振り）/ CAPTURE（カメラ） |
| CoreS3 単体（サーボ無し） | `XangiBridge` | 921600 | WAV / FACE / CAPTURE（MOVE は unavailable） |
| AtomS3R + Atomic Voice Base / Echo Base | `AtomVoiceBridge` | 115200 | WAV / FACE（MOVE / CAPTURE は unavailable） |

入手先: M5Stack 公式ストア / スイッチサイエンス。K151-R が最も機能フル（首振りまで動く）。

## Step 2: ファームを焼く

PlatformIO で `examples/XangiBridge` または `examples/AtomVoiceBridge` を焼く。

```bash
git clone https://github.com/karaage0703/xangi-stackchan.git
cd xangi-stackchan

# K151 / K151-R / CoreS3 の場合
pio run -d examples/XangiBridge -t upload

# AtomS3R + Voice/Echo Base の場合
pio run -d examples/AtomVoiceBridge -t upload
```

サーボ・カメラの有無は起動時に自動検出 → 無いハードでも `MOVE` / `CAPTURE` が unavailable 応答するだけで他は動く（graceful degradation）。

## Step 3: PC 側のセットアップ

`uv` で xangi-stackchan を取得して TTS（piper-plus）+ つくよみちゃんモデルをセットアップ:

```bash
cd xangi-stackchan
uv sync
./scripts/setup_piper.sh   # piper-plus CLI + モデルを自動 DL
```

`tools/piper` ラッパーが生成される。

> **`piper failed: ... Opset 5 ... opset 3 only` エラーが出たら**: 初回最適化キャッシュが onnxruntime と非互換。`rm models/*.cpu.opt.onnx*` で解消。

## Step 4: xangi 側を確認

bridge は xangi の `GET /api/events/stream`（pull 型 SSE）を購読する。xangi 側で events が有効になってるか確認:

```bash
# xangi の .env に以下が無ければ追記（デフォルト有効）
# XANGI_EVENTS_ENABLED=true

# 接続テスト
curl -sI http://127.0.0.1:18888/api/events/stream | head -1
# → HTTP/1.1 200 OK が返れば OK
```

## Step 5: udev で USB デバイスに固定名を割り当てる（推奨）

USB 抜き差しで `/dev/ttyACMx` の番号がブレるのを避ける。`udev/` ディレクトリにルールサンプルがあるので参考に:

```bash
sudo cp xangi-stackchan/udev/99-xangi-stackchan.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
ls -l /dev/stackchan   # シンボリックリンクが出来てれば OK
```

## Step 6: bridge を常駐起動

ターミナル終了で落ちないよう `setsid -f` で常駐:

```bash
cd xangi-stackchan
setsid -f bash -c 'cd '"$PWD"' && exec uv run xangi-stackchan \
  --xangi-url http://127.0.0.1:18888 \
  --port /dev/stackchan \
  --baud 921600 \
  --volume 200 \
  --tts piper \
  --stackchan-retry-seconds 3 \
  --settings-port 7897' </dev/null >>/tmp/xangi-stackchan.log 2>&1
```

オプション要点:

- `--baud`: `921600`（CoreS3 系）/ `115200`（AtomS3R 系）
- `--volume`: 0〜255、AtomS3R + Voice Base は ES8311 過変調防止で 192 以下推奨
- `--tts`: `piper` / `voicevox` / `none`

ログ確認:

```bash
tail -f /tmp/xangi-stackchan.log
```

## Step 7: 設定 UI からチューニング

ブラウザで <http://127.0.0.1:7897/> を開くと以下が変更できる:

- xangi URL / thread filter
- USB 接続先・音量
- TTS 設定（piper / voicevox / none）
- 状態ごとの表情（idle / thinking / talking / error）
- 首振り（MOVE）設定（サーボあり機のみ）
- カメラスナップショット（Phase 1A）

保存すると `~/.xangi/xangi-stackchan/config.json` に永続化、実行中の bridge にもライブ反映する。

## Step 8: 動作確認

モード A/B/C で xangi に何か話しかける → 数秒以内にスタックチャンが:

1. **thinking 表情** に切り替わる（応答生成中）
2. **TTS 音声** が再生される（talking 表情 + 口パク + 首振り）
3. 完了したら **idle 表情** に戻る

エラー時は `error` 表情。

ダンスデモ単体テスト:

```bash
curl -X POST http://127.0.0.1:7897/api/dance-demo
```

## Step 9: トラブル対処

| 症状 | 対処 |
|------|------|
| bridge が xangi に接続できない | `XANGI_EVENTS_ENABLED=true` を `.env` に明示、xangi 再起動 |
| `/dev/stackchan: Permission denied` | `sudo usermod -aG dialout $USER` → ログアウト・再ログイン |
| TTS が再生されない | `--tts piper` 指定 + `setup_piper.sh` が完走しているか、`tools/piper` が生成されているか確認 |
| 音が割れる（AtomS3R + Voice Base） | `--volume 192` 以下に下げる（ES8311 過変調防止） |
| 表情が切り替わらない | 設定 UI で「状態ごとの表情」が割り当てられているか確認 |
| ファーム焼き失敗 | M5Stack のブートモード（BtnA 押しながら USB 接続）で再試行 |

## 次の一歩

- **複数台連動** — XangiBridge ファームは `--instance-id` で 1 PC から複数台同時制御可能（PR #26 で対応）
- **カメラ連動** — K151 / CoreS3 系の CAPTURE 機能で、xangi に画像を送って画像分析させる（要マルチモーダルモデル）
- **VOICEVOX** — `--tts voicevox` でずんだもん等の他キャラ声に切り替え

詳細は <https://github.com/karaage0703/xangi-stackchan/blob/main/docs/usage.md> 参照。

## 出力フォーマット

セットアップ完了報告:

```
xangi-stackchan 連動完了（モード D）

接続先 xangi: http://127.0.0.1:18888
ハード: <K151-R / CoreS3 単体 / AtomS3R + Voice Base>
TTS: <piper / voicevox / none>
設定 UI: http://127.0.0.1:7897/
ログ: tail -f /tmp/xangi-stackchan.log

最初に試して: xangi に話しかける → スタックチャンが応答を喋る
停止: pkill -f xangi-stackchan
```

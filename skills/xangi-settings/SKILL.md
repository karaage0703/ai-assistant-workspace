---
name: xs:xangi-settings
description: xangiの設定をチャットから動的に変更するスキル。.envファイルの編集と再起動を行う。「このチャンネルでも応答して」「タイムアウト変えて」「設定確認して」で使用。ローカル実行専用（Docker環境では使用不可）。
---

# xangi 設定変更スキル

チャットからxangiの設定（.envファイル）を動的に変更する。

## 前提条件

- **ローカル実行のみ対応**（Docker環境では.envを変更できない）
- xangiの.envファイルパス: xangiのルートディレクトリに配置

## ⚠️ 最重要: 自分のインスタンス特定（設定変更前に必ず実行！）

複数のxangiインスタンスが同一マシンで動いている場合がある。
**間違ったインスタンスの.envを変更すると意味がない。**

### 特定手順

```bash
# 1. xangi関連の.envファイルを一覧
ls ~/xangi*/.env 2>/dev/null

# 2. 各.envのWORKSPACE_PATHを確認して、自分のワークスペースと一致するものを特定
grep WORKSPACE_PATH ~/xangi*/.env
```

### 判定ロジック

1. 自分の `WORKSPACE_PATH`（= このリポジトリのルート）と一致する `.env` を探す
2. 複数ある場合は、プロセス一覧から起動元ディレクトリを確認
3. **特定できたら、そのパスを使って設定変更する**

---

## 実行フロー

### Step 0: 自分のインスタンスを特定（上記手順）

### Step 1: 要望の種類を判定

- **設定確認** → Step 2a
- **設定変更** → Step 2b

### Step 2a: 設定確認

```bash
# 現在の設定を確認（トークン等はマスク）— パスはStep 0で特定したものを使う
cat /path/to/xangi/.env | grep -v TOKEN | grep -v "^#" | grep -v "^$"
```

**出力フォーマット:**
```
📋 xangi 現在の設定

**Discord:**
- AUTO_REPLY_CHANNELS: 123456789, 987654321
- DISCORD_STREAMING: true

**AI設定:**
- AGENT_BACKEND: claude-code
- TIMEOUT_MS: 300000

※ トークン類は非表示
```

### Step 2b: 設定変更

1. **変更内容を確認**: ユーザーの意図を把握
2. **対象変数を特定**: `[SKILL_DIR]/references/env-variables.md` を参照
3. **現在値を確認**: .envファイルを読む
4. **.envを編集**: 該当行を更新（なければ追加）
5. **変更を報告**:

```
✅ 設定を変更しました

**変更内容:**
- AUTO_REPLY_CHANNELS: (なし) → 123456789,987654321

⚠️ 反映には再起動が必要です。再起動しますか？
```

6. **再起動**: ユーザーの承諾後、`SYSTEM_COMMAND:restart` を送信

## よくある変更パターン

### チャンネル追加（メンションなしで応答）

```
「#generalでも反応して」
→ AUTO_REPLY_CHANNELS にチャンネルIDを追加
```

### タイムアウト変更

```
「タイムアウトを10分に」
→ TIMEOUT_MS=600000 に変更
```

### ストリーミング切り替え

```
「ストリーミングオフにして」
→ DISCORD_STREAMING=false に変更
```

### 思考表示切り替え

```
「考え中アニメーションにして」
→ DISCORD_SHOW_THINKING=false に変更
```

## 注意事項

- **トークン類は絶対に変更・表示しない**
  - `DISCORD_TOKEN`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
- **許可ユーザーIDは慎重に**
  - `DISCORD_ALLOWED_USER`, `SLACK_ALLOWED_USER`
- 変更後は必ず再起動が必要

## Docker環境での代替案

Docker環境では.envを直接変更できないため：

```
⚠️ Docker環境では設定を動的に変更できません。

**代替方法:**
1. ホスト側で .env を編集
2. `docker compose restart` でコンテナ再起動
```

## 使用例

```
xangiの設定確認して
このチャンネルでも反応するようにして（チャンネルID: 123456789）
タイムアウトを10分に変更して
ストリーミング出力をオフにして
```

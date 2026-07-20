---
name: xs-multi-agent
description: 複数のAIエージェント（自分/Codex/Claude/Grok/Cursor/Antigravity等）で協調して考える・調査する・レビューする。最初に利用可能エージェントを検出して設定ファイルを作成・更新し、使える相手へ依頼する。「みんなで考えて」「マルチエージェントで分析して」「複数のAIでレビューして」と言われたら使う。
---

# マルチエージェント協調スキル

複数のAIエージェントを使って、より深い分析・多角的な視点を得る。

重要: このスキルは毎回、最初に利用可能エージェントを検出する。CLIの入れ替わり、ログイン状態、クォータ、環境差を固定表で決め打ちしない。

## 最初に必ずやること

```bash
bash [SKILL_DIR]/scripts/check_agents.sh
```

このコマンドは、各エージェントに軽いプロンプトを投げ、`skills/xs-multi-agent/SKILL.md` を読めるかまで確認する。単なる挨拶応答ではなく、スキル文脈を読める最低限の実用チェックにする。各サービスのクォータを少量使う。

軽量にコマンド存在とバージョンだけ見たい時:

```bash
bash [SKILL_DIR]/scripts/check_agents.sh --no-smoke
```

このコマンドは `$STATE_DIR/multi-agent/agents.json` を作成・更新し、生成したパスを出力する。

`STATE_DIR` は `STATE_DIR="${STATE_DIR:-${WORKSPACE_PATH:-$HOME}/.xangi}"` として扱う。`WORKSPACE_PATH` が未設定なら `$HOME/.xangi/multi-agent/agents.json` に保存される。設定ファイルはランタイム状態なので git 管理しない。

## 設定ファイルの見方

- `available: true`: コマンドがPATH上にあり、最低限のバージョン取得に成功
- `ready: true`: smoke 実行時に短い依頼が成功
- `ready: false`: smoke 実行時にログイン切れ、usage limit、実行失敗を検出
- `ready: null`: `--no-smoke` 実行時など、実依頼の疎通は未確認
- `recommended: true`: 通常の依頼先候補
- `scope: current_turn`: 現在のセッション内だけ有効
- `volatile: true`: セッション、チャンネル、モデル、プロンプトで実体が変わる
- `ready_agents`: 動作確認に成功した外部エージェント
- `usable_agents`: `ready=true` かつ `recommended=true` の標準外部依頼先

## 利用可能なエージェント

固定表ではなく、`scripts/check_agents.sh` の検出結果を使う。現在の検出対象:

| ID | 位置づけ | 標準扱い |
|----|----------|----------|
| `self` | 現在のAIセッション。調整役・統合役 | 候補配列には入れない |
| `codex` | 設計判断、デバッグ、深い推論、コードレビュー | 推奨 |
| `claude` | 広い推論、文章化、レビュー | 推奨（クォータ注意） |
| `grok` | 別視点の設計・レビュー、実装案 | 推奨 |
| `cursor` | codebase Q&A、plan/ask modeレビュー | 推奨 |
| `antigravity` | Antigravity CLI | 推奨（smoke pass時のみ） |

追加・削除が必要になったら、`scripts/check_agents.sh` と `scripts/run_agent.sh` の両方を更新する。

## ワークフロー

### 0. エージェント検出・設定更新

1. `bash [SKILL_DIR]/scripts/check_agents.sh` を実行
2. 出力された `agents.json` を読む
3. `usable_agents` を外部依頼先の基本候補にする
4. `ready=false` はそのターンでは使わない
5. `self` は現在ターンの調整役として扱い、外部依頼先リストには混ぜない

例:

以下はLinux / WSLの例。`setsid` がないmacOSではlaunchdなどservice managerを使う。

```bash
CONFIG_PATH="$(bash skills/xs-multi-agent/scripts/check_agents.sh)"
cat "$CONFIG_PATH"
```

### 0.5. 依頼プロンプトをファイル化

CLIごとに引用符、改行、長文引数で事故りやすい。依頼内容は `/tmp` にファイル化して渡す。

```bash
cat > /tmp/multi-agent-prompt.txt <<'EOF'
<依頼内容>
EOF
```

短時間の依頼は補助スクリプトで実行する。

```bash
bash skills/xs-multi-agent/scripts/run_agent.sh codex /tmp/multi-agent-prompt.txt "$PWD"
bash skills/xs-multi-agent/scripts/run_agent.sh grok /tmp/multi-agent-prompt.txt "$PWD"
bash skills/xs-multi-agent/scripts/run_agent.sh cursor /tmp/multi-agent-prompt.txt "$PWD"
```

`run_agent.sh` は短時間・foreground・読み取り寄りの依頼用。複数分以上かかる分析や実装を任せる場合は、下の「回答待ちのルール」に従う。

### 1. リサーチモード

調査・情報収集が必要なとき:

1. まず自分で初期調査
2. 検出済みの推奨エージェントから1〜3個に別視点で調査依頼
3. 結果を統合してまとめる

### 2. レビューモード

コードや文章のレビュー:

1. 自分でまずレビュー
2. Codex / Grok / Cursor など、検出済みの推奨エージェントにレビュー依頼
3. 重要度順に findings を統合して報告

レビュー依頼時は、各エージェントに「バグ・リスク・回帰・不足テストを優先。好みの指摘は後回し」と明示する。

### 3. ブレインストームモード

アイデア出し・深い分析:

1. 自分でまず考える
2. 使えるエージェントに同じ問い、または役割別の問いを投げる
3. 意見の相違点・共通点を整理
4. 統合した結論を出す

## 注意

- Codex CLI は `codex exec --skip-git-repo-check --sandbox danger-full-access --cd <workspace> - < prompt.txt` で非インタラクティブ実行する
- Claude Code は `claude -p "<prompt>" --add-dir <workspace>` で非インタラクティブ実行する。`XANGI_ENV_FILE`、`[WORKSPACE]/.env`、`$HOME/.xangi/.env` に `ANTHROPIC_API_KEY` / `CLAUDE_CODE_BARE=true` / `CLAUDE_CODE_MAX_BUDGET_USD` があれば `run_agent.sh` が読み込む
- Grok CLI は `grok -p "<prompt>" --permission-mode plan` を標準にする
- Cursor Agent は `cursor-agent --print --mode=ask` を標準にする
- Antigravity CLI は `ready=true` なら標準依頼先に含める。空出力・quota 429・認証エラーを成功扱いしない
- 結果は必ず統合して、ユーザーにわかりやすくまとめる
- 各エージェントの意見が違う場合は、両論併記する
- 外部エージェントが0件でも、`self` だけで進める。その場合は「検出したが外部エージェントは使えなかった」と明示する

## 回答待ちのルール

AIアシスタントのセッションは turn-based。外部AIプロセスを起動したまま turn を閉じると、結果回収できないことがある。所要時間で分岐する。

### 短時間（60秒目安）: turn 内で待つ

- 単発の質問・短い回答想定なら `scripts/run_agent.sh` をforegroundで実行し、同じ turn 内で結果を受け取る
- 結果が返ったら統合してそのターンで報告
- 複数エージェントを使うなら、時間を見て1件ずつ実行するか、foregroundで並列起動して同じ turn 内で必ず回収する

### 長時間（複数分以上想定）: 復帰導線を作る

並列に大規模分析させる場合は、turn を跨ぐ前提で組む。

1. `setsid bash -lc` で親process groupから分離し、PID・ログ・終了コードを保存する
2. 開始報告前に `ps` で別SID/PGIDと生存を確認する
3. xangi環境なら、子プロセスが終了状態を保存した後に `xangi-cmd trigger` を呼ぶ。定刻確認なら `schedule_add` を使う
4. ログパス、復帰方法、確認コマンドをユーザーに伝える

例:

```bash
AGENT_STATE_DIR="$(mktemp -d)"
setsid bash -lc '
  state_dir="$1"
  agent="$2"
  prompt_file="$3"
  workspace="$4"
  echo $$ > "$state_dir/pid"
  bash skills/xs-multi-agent/scripts/run_agent.sh "$agent" "$prompt_file" "$workspace" > "$state_dir/output.log" 2>&1
  rc=$?
  echo "$rc" > "$state_dir/exit"
  # xangiでは終了状態保存後に xangi-cmd trigger を呼ぶ
  exit "$rc"
' bash "$AGENT_STATE_DIR" codex /tmp/multi-agent-prompt.txt "$PWD" >/dev/null 2>&1 &

sleep 2
ps -o pid,ppid,sid,pgid,stat,etime,cmd -p "$(cat "$AGENT_STATE_DIR/pid")"
echo "State: $AGENT_STATE_DIR"
```

「結果が来たら統合します」と書くなら、schedule / trigger / ユーザーへの明示的なハンドオフのどれかを必ず作る。

### やってはいけないこと

- バックグラウンドタスクIDを「自走」と勘違いして turn を閉じる
- 結果が来ないまま「統合結果」を報告する
- 存在しない `process poll` / `process log` コマンドを書く
- `self` を外部エージェントとして保存し、次回以降の依頼先にする

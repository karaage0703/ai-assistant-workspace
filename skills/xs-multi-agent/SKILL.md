---
name: xs-multi-agent
description: 異なるproviderのAI（Codex/Claude/Grok/Cursor/Antigravity等）から独立意見を集め、共通論点で相互検討して統合する。最初に利用可能エージェントを検出する。「みんなで考えて」「マルチエージェントで分析して」「複数のAIでレビューして」と言われたら使う。
---

# マルチエージェント協調スキル

異なるAI providerから独立意見を得て、共通論点で考えた結果を統合する。
同じproviderの子エージェントを増やすだけの並列処理とは区別する。

重要: このスキルは毎回、最初に利用可能エージェントを検出する。CLIの入れ替わり、ログイン状態、クォータ、環境差を固定表で決め打ちしない。

## 最初に必ずやること

```bash
bash [SKILL_DIR]/scripts/check_agents.sh
```

このコマンドは、各エージェントに軽いプロンプトを投げ、`skills/xs-multi-agent/SKILL.md` を読めるかまで確認する。成功判定には固定トークン `CHECK_AGENTS_OK` を使い、解釈差のある自然言語回答を判定に使わない。各サービスのクォータを少量使う。

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
- `provider_family`: OpenAI / Anthropic / xAI / Google等の独立性を判定する単位
- 複数providerのモデルを選べるCLIは、実providerを証明できるまで`unknown`としてpanel票に数えない
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
6. `ready=true` は短いsmoke成功だけを意味する。今回必要なネットワーク、workspace読取、filesystem watchまでは保証しない

例:

以下はLinux / WSLの例。`setsid` がないmacOSではlaunchdなどservice managerを使う。

```bash
CONFIG_PATH="$(bash skills/xs-multi-agent/scripts/check_agents.sh)"
cat "$CONFIG_PATH"
```

### 0.5. 依頼プロンプトをファイル化

CLIごとに引用符、改行、長文引数で事故りやすい。依頼内容は `/tmp` にファイル化し、依頼に必要な最小ディレクトリを明示して渡す。

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

対象workspaceは必須。調整役のworkspaceを既定で丸ごと渡さない。`run_agent.sh` は空回答、途中終了、permission blocker、filesystem watch失敗を非0終了にする。一定量の根拠が必要なら `MULTI_AGENT_MIN_OUTPUT_BYTES=500` のように最小出力量を指定する。

### 0.75. 目的と成功条件を固定

「みんなで調べて考えて」の既定目的は、単なる作業分散ではなく異なるproviderの見方を同じ判断へ反映すること。

- 調査対象と、最後に全員へ答えてもらう共通の判断質問を決める
- 成功条件は、外部2エージェント以上かつ異なる`provider_family` 2系統以上が共通の`synthesis`へ有効回答すること
- 同じproviderの子エージェントを別の一票として数えない
- 分担調査だけで終わらず、検証済み材料を共有して同じ統合質問へ独立回答を取る

### 1. リサーチモード

調査・情報収集が必要なとき:

1. まず自分で初期調査
2. 検出済みの推奨エージェントから1〜3個に別視点で調査依頼
3. 各成果物が根拠URLまたは対象ファイル、依頼した評価軸を含むか確認する
4. 検証済み材料を共通資料にして、異なるproviderへ同じ統合質問を渡す
5. 結果manifestを作り、panel検証後に統合する

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

### 4. 成果manifestとpanel検証

各成果物をファイルへ保存し、TSVへ状態を記録する。

```text
agent_id	phase	status	role	evidence_path
codex	synthesis	success	統合判断	/tmp/synthesis-codex.txt
claude	synthesis	success	統合判断	/tmp/synthesis-claude.txt
```

```bash
bash [SKILL_DIR]/scripts/validate_panel.sh \
  --phase synthesis --min-success 2 --min-families 2 \
  "$CONFIG_PATH" /tmp/multi-agent-results.tsv
```

panelは`agents.json`で`ready=true`の外部agentだけを数え、同じevidence fileを相対パス・symlink等で複数agentの成果として再利用する行を拒否する。これは実行manifestの整合性ゲートであり、providerの暗号学的な身元証明ではない。

検証失敗時も単独の暫定分析は返してよいが、「みんなの結論」「合意」とは表現しない。成功・失敗したproviderと不足視点をそのまま報告する。

## 注意

- Codex CLI は最終回答ファイルだけを成果物として返し、大量の探索ログを混ぜない
- Claude Code は対象workspaceでsafe/read-only寄りのツールだけを許可する。認証情報は既にexportされた環境変数を使う。別ファイルから読む必要がある場合だけ、ユーザーが明示した `MULTI_AGENT_ENV_FILE` から `ANTHROPIC_API_KEY` / `CLAUDE_CODE_MAX_BUDGET_USD` を限定して読み込む
- Grok CLI はplan mode、memory/subagent無効、read/search/Web取得だけを標準にする
- Cursor Agent はask mode、Autoモデル、明示workspaceを標準にする。非対話実行のため`--trust`を使うので、信頼できる対象workspaceだけを渡す
- Antigravity CLI はGoogle Geminiモデルを明示したsmokeが`ready=true`の場合だけGoogle provider票として扱う。既定は`gemini-3.1-pro-low`で、`MULTI_AGENT_ANTIGRAVITY_MODEL`により別のGeminiモデルを指定できる。空出力・quota 429・認証エラーを成功扱いしない
- 結果は必ず統合して、ユーザーにわかりやすくまとめる
- 各エージェントの意見が違う場合は、両論併記する
- 外部エージェントが0件でも、`self` だけで進める。その場合は「検出したが外部エージェントは使えなかった」と明示する

## 完了前チェックリスト

- `check_agents.sh` / `run_agent.sh`を変更した場合、PATH上で`available=true`の全agent IDを実CLI smokeし、成功・失敗理由をagent別に確認した
- 各担当の終了コードと最終成果物を確認した
- blocker、途中終了、既知runtime errorを成功数に含めていない
- 調査成果物に根拠URLまたは対象ファイルがある
- `validate_panel.sh`で目的phaseの異なるprovider 2系統以上を確認した
- 分担調査だけでなく、共通質問への独立した統合回答を回収した
- 検証済み成果だけを統合した

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
3. xangi環境なら、子プロセスが終了状態を保存した後に `xangi tool trigger` を呼ぶ。定刻確認なら `schedule_add` を使う
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
  # xangiでは終了状態保存後に xangi tool trigger を呼ぶ
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

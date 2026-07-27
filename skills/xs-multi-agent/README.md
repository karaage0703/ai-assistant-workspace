# xs-multi-agent

複数のAI CLIを「入っているはず」で決め打ちせず、その時点で使える相手だけを検出して協調分析するスキルです。

実行にはBash 4以降、`jq`、`timeout`が必要です。`validate_panel.sh` の証拠ファイル同一性確認はGNU `realpath` / `stat`を使うため、Linux / WSL向けです。macOSではGNU coreutilsを導入してPATHを通してください。各AI CLIは必要なものだけインストールしてください。未インストールのCLIは自動的に候補から外れます。
Codexはread-only sandboxで起動します。認証情報は既にexportされた環境変数を使い、必要な場合だけ`MULTI_AGENT_ENV_FILE`を明示します。対象workspaceの`.env`は自動で読みません。
Antigravityはproviderを曖昧にしないため、既定でGoogle Geminiの`gemini-3.1-pro-low`を明示します。別のモデルを使う場合は`MULTI_AGENT_ANTIGRAVITY_MODEL`で指定できますが、`gemini-*`以外はproviderが`unknown`となりpanel票には数えません。

## 主要な考え方

- コマンドの存在だけでなく、短いsmokeでログイン・クォータ・runtime failureも確認する
- 調整役と対象workspaceを分離し、依頼に必要な最小ディレクトリだけを渡す
- CLIの終了コード0だけで成功とせず、空回答・途中終了・permission blockerを除外する
- 同じproviderの複数agentを独立意見として水増ししない
- 分担調査後、異なるproviderへ同じ統合質問を渡して結果を機械検証する

## 利用可能agentの確認

```bash
bash skills/xs-multi-agent/scripts/check_agents.sh
```

クォータを使わず、コマンドとバージョンだけ確認する場合:

```bash
bash skills/xs-multi-agent/scripts/check_agents.sh --no-smoke
```

結果は `$STATE_DIR/multi-agent/agents.json` に保存されます。`ready=true` かつ `recommended=true` のagentだけが `usable_agents` に入ります。外部agentが0件でも、現在のAIセッションだけで作業を継続できます。

## 短時間の依頼

```bash
cat > /tmp/multi-agent-prompt.txt <<'EOF'
この設計のリスクをレビューしてください。バグ、運用事故、不足テストを優先してください。
EOF

TARGET_WORKSPACE="$(git rev-parse --show-toplevel)"
bash skills/xs-multi-agent/scripts/run_agent.sh codex /tmp/multi-agent-prompt.txt "$TARGET_WORKSPACE"
```

根拠を含む一定量の報告が必要なら、最小出力量を指定します。

```bash
MULTI_AGENT_MIN_OUTPUT_BYTES=500 \
  bash skills/xs-multi-agent/scripts/run_agent.sh codex /tmp/multi-agent-prompt.txt "$TARGET_WORKSPACE"
```

## panel検証

各成果物を保存し、次の5列を持つTSVを作ります。

```text
agent_id	phase	status	role	evidence_path
```

異なるprovider 2系統以上の有効成果があるか確認します。

```bash
bash skills/xs-multi-agent/scripts/validate_panel.sh \
  --phase synthesis --min-success 2 --min-families 2 \
  "$STATE_DIR/multi-agent/agents.json" /tmp/multi-agent-results.tsv
```

`agents.json`で`ready=true`の外部agentだけを数え、同じevidence fileを相対パスやsymlinkで複数agentの成果として使い回す行は拒否します。これは実行manifestの整合性ゲートであり、providerの暗号学的な身元証明ではありません。

検証を通らない場合は単独または限定的な分析として扱い、「複数AIの合意」とは表現しません。
Cursorなどproviderが`unknown`のagentは調査には使えますが、異なるproviderを保証するpanel票には数えません。

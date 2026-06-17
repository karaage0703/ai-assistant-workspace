# xangi 環境変数リファレンス

## Discord設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `DISCORD_TOKEN` | Discord Bot Token | 必須 |
| `DISCORD_ALLOWED_USER` | 許可ユーザーID | 必須 |
| `AUTO_REPLY_CHANNELS` | メンションなしで応答するチャンネルID（カンマ区切り） | なし |
| `DISCORD_STREAMING` | ストリーミング出力 | `true` |
| `DISCORD_SHOW_THINKING` | 思考過程を表示 | `true` |

## Slack設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `SLACK_BOT_TOKEN` | Slack Bot Token (xoxb-...) | - |
| `SLACK_APP_TOKEN` | Slack App Token (xapp-...) | - |
| `SLACK_ALLOWED_USER` | Slack許可ユーザーID | - |
| `SLACK_AUTO_REPLY_CHANNELS` | メンションなしで応答するチャンネルID | - |
| `SLACK_REPLY_IN_THREAD` | スレッド返信するか | `true` |
| `SLACK_STREAMING` | ストリーミング出力 | `true` |
| `SLACK_SHOW_THINKING` | 思考過程を表示 | `true` |

## AIエージェント設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `AGENT_BACKEND` | AI CLI (`claude-code` / `codex`) | `claude-code` |
| `AGENT_MODEL` | 使用モデル | バックエンド依存 |
| `TIMEOUT_MS` | タイムアウト（ミリ秒） | `300000` (5分) |
| `WORKSPACE_PATH` | 作業ディレクトリ | `./workspace` |
| `SKIP_PERMISSIONS` | デフォルトで許可スキップ | `false` |

## 注意事項

- Docker環境ではコンテナ内から.envを変更できない
- ローカル実行時のみ動的設定変更が可能
- 変更後は `SYSTEM_COMMAND:restart` で再起動が必要

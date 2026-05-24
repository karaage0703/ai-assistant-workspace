# モード C: Docker（フル compose）— セキュア・上級者向け

> **対象**: 本番運用したい人 / セキュリティ重視 / LAN/WAN 公開したい
> **所要時間**: 30 分〜数時間（公開構成による）
> **前提**: Docker, git, 空き 20GB+、リバースプロキシ知識（公開する場合）

完全カスタム `.env`、本番運用、認可・公開範囲制御、常駐化までやり切るモード。

## Step 1: 前提チェック

```bash
docker --version && docker compose version
git --version
df -h ~ | tail -1                   # 20GB+ 推奨
nvidia-smi 2>/dev/null || echo "GPU なし"
ufw status 2>/dev/null              # ファイアウォール状況
```

事前に決めておくこと:

- 公開範囲（localhost only / LAN / WAN）
- リバースプロキシの方針（Caddy / Nginx / なし）
- バックエンド（local-llm / claude-code）
- 利用者の Discord ID リスト

## Step 2: clone と .env テンプレ準備

```bash
mkdir -p ~/xangi-prod && cd ~/xangi-prod
git clone https://github.com/karaage0703/xangi.git
cd xangi
cp .env.example .env
chmod 600 .env       # 権限を絞る
```

## Step 3: バックエンド選択と .env チューニング

```bash
# ===== .env =====

# --- Backend ---
AGENT_BACKEND=claude-code            # 品質重視なら claude-code
# AGENT_BACKEND=local-llm
# LOCAL_LLM_MODEL=gemma4:26b
# LOCAL_LLM_NUM_CTX=16000

# --- Discord（使う場合） ---
DISCORD_TOKEN=...
DISCORD_ALLOWED_USER=111111111111,222222222222   # カンマ区切り複数可
DISCORD_ALLOWED_CHANNELS=...

# --- Web チャット ---
WEB_CHAT_ENABLED=true
WEB_CHAT_PORT=18888
WEB_CHAT_BIND=127.0.0.1              # 外に出さない（reverse proxy 前提）

# --- Workspace ---
WORKSPACE_PATH=./ai-assistant-workspace

# --- ログ・タイムアウト ---
LOG_LEVEL=info
RESPONSE_TIMEOUT=300
```

## Step 4: 認可・公開範囲

**ローカル限定 (推奨初期構成):**

- `WEB_CHAT_BIND=127.0.0.1` でホスト外に出さない
- Discord 側は `DISCORD_ALLOWED_USER` で利用者を限定

**LAN / WAN 公開する場合:**

1. リバースプロキシで SSL 終端 + Basic 認証

   ```caddy
   # Caddyfile 例
   xangi.example.com {
     basicauth { user $2a$14$... }
     reverse_proxy 127.0.0.1:18888
   }
   ```

2. ファイアウォールで 18888 を直公開しない（`ufw deny 18888`）
3. 必要なら Cloudflare Tunnel / Tailscale 経由でゼロトラスト化

## Step 5: 永続化とバインドマウント

`docker/docker-compose.yml` のボリュームを確認、必要に応じて bind mount に変更:

- `ai-assistant-workspace/` → ホスト側で git 管理（`quickstart.sh` のように `.git` を消さない構成にする）
- Ollama モデルキャッシュ → 名前付きボリュームで永続化（再起動・他インスタンスと共有可）
- ログ → ホスト側ディレクトリにマウントしてローテ可能に

```yaml
# 例: docker-compose.override.yml
services:
  xangi:
    volumes:
      - ./ai-assistant-workspace:/app/ai-assistant-workspace
      - ./logs:/app/logs
  ollama:
    volumes:
      - ollama-models:/root/.ollama
volumes:
  ollama-models:
```

## Step 6: 起動

```bash
docker compose up -d
docker compose ps
docker compose logs -f xangi
```

ヘルスチェック:

```bash
curl -sI http://127.0.0.1:18888/ | head -1     # 200 OK か
```

## Step 7: 常駐化（再起動時自動起動）

**Docker daemon の自動起動:**

```bash
sudo systemctl enable docker
```

**compose の restart ポリシー** を `docker-compose.yml` で `restart: unless-stopped` に。

**ヘルスチェック + 自動再起動** を必要なら systemd unit にラップ:

```ini
# /etc/systemd/system/xangi.service
[Unit]
Description=xangi (docker compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory=/home/<user>/xangi-prod/xangi
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now xangi.service
```

## Step 8: 監視・ログ

```bash
# リソース
docker stats --no-stream

# ログ追跡
docker compose logs -f xangi --tail 200

# Ollama VRAM
docker exec ollama ollama ps

# ログローテ (host 側)
sudo cat <<'EOF' > /etc/logrotate.d/xangi
/home/<user>/xangi-prod/xangi/logs/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
EOF
```

## Step 9: アップデート・バックアップ

```bash
# 更新（ダウンタイム ~30s）
git pull
docker compose pull
docker compose up -d --build

# バックアップ対象
# - .env（権限 600 のまま暗号化保管推奨）
# - ai-assistant-workspace/（git remote に push が安全）
# - logs/ memory/（必要なら）
```

破壊的変更が入ることもあるので `git log --oneline upstream/main` で CHANGELOG を確認してから up。

## Step 10: 上級者向けの発展

- **マルチインスタンス連動** — xangi を 2 つ立てて `inter-instance-chat` で会話させる
- **xangi-pets** — デスクトップマスコット連動
- **xangi-stackchan** — スタックチャン（M5Stack 単体ロボット）連動。詳細は `references/mode-d-stackchan.md`
- **Claude API キーローテーション** — `.env` の API キーを定期更新する仕組み
- **モデルプリロード** — Ollama に複数モデルを置いて用途別に切替（`LOCAL_LLM_MODEL` を起動時上書き）
- **専用 Discord サーバー** — チャンネル別に役割を分けて運用（雑談 / 仕事 / 通知）

## Step 11: トラブル対処（モード C 特有）

| 症状 | 対処 |
|------|------|
| `permission denied` for bind mount | host 側ディレクトリの所有者・mode を確認、`chown -R $USER:$USER` |
| Caddy / Nginx 経由で 502 | `WEB_CHAT_BIND=0.0.0.0` を一旦試す or proxy 側 `host.docker.internal` 設定確認 |
| Ollama VRAM 不足 | `LOCAL_LLM_NUM_CTX` を下げる / モデルを軽量化 / 同時起動モデル数を制限 |
| systemd 起動失敗 | `journalctl -u xangi.service` で原因確認、`WorkingDirectory` のパス・compose ファイル存在を再確認 |

詳細は [docs/usage.md](https://github.com/karaage0703/xangi/blob/main/docs/usage.md) を参照。

## 出力フォーマット

セットアップ完了報告:

```
xangi 起動完了（Docker フル）

エンドポイント: <URL or 127.0.0.1:18888>
バックエンド: <local-llm / claude-code>
公開範囲: <localhost / LAN / WAN via reverse proxy>
常駐: systemd / restart=unless-stopped
ログ: docker compose logs -f xangi
停止: sudo systemctl stop xangi.service
```

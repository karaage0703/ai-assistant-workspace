# triggers

**LLMがFunction Callingで呼び出す軽量ツール**を置く場所。スキルとツール呼び出しの中間に位置する仕組みで、ローカルLLMのように性能が限定的なモデルでも「再現性高く決まった処理」を実行できるように設計されている。

[xangi](https://github.com/karaage0703/xangi) と組み合わせて使う想定。コンセプトの詳細は [Trigger: ローカルLLM用簡易スキルシステム](https://zenn.dev/karaage0703/articles/89631872ca5a86) を参照。

## どう動くか

1. ユーザーがチャットで自然言語で発話する（例: 「名古屋の天気は？」）
2. LLMが各 `trigger.yaml` の `description` を見て、関連するトリガーがあるか判断
3. 関連すれば Function Calling で `handler.sh` を呼ぶ（引数も自動生成）
4. `handler.sh` の標準出力をLLMが受け取り、ユーザーへの応答に活用

トリガーは LLM の Function Calling 経由で呼ばれることを前提とした仕組み。xangi の場合、ローカルLLM向け機能（`LOCAL_LLM_TRIGGERS=true`）として使われる。

## triggers と skills の違い

| | triggers | skills |
|---|---|---|
| 実行 | LLMがFunction Callingで呼ぶ | AI（LLM）が読み込んで段階的に実行 |
| 形式 | `handler.sh` + `trigger.yaml` | `SKILL.md`（プロンプト+補助スクリプト） |
| LLMの関与 | description見て呼ぶか判断するだけ | プロンプトを読み込んで都度推論 |
| 柔軟性 | 固定処理（引数だけ可変） | 自然言語の揺らぎに対応・複数ステップ |
| 適している用途 | 天気・ニュース・検索など決まった取得処理 | 文章生成・要約・判断・対話・ワークフロー |

ざっくり言うと、**トリガーは「LLMが叩ける固定ツール」**、スキルは「LLMが読み込んで判断するプロンプト」。判断・生成が必要ならスキル、決まった処理ならトリガー。

## ディレクトリ構成

```
triggers/
├── README.md           # このファイル
├── rag/                # ワークスペースRAG検索
│   ├── trigger.yaml
│   ├── handler.sh
│   └── README.md
├── technews/           # テックニュース取得
│   ├── trigger.yaml
│   ├── handler.sh
│   └── README.md
└── weather/            # 天気予報
    ├── trigger.yaml
    ├── handler.sh
    └── README.md
```

各トリガーは独立したディレクトリ。最低限 `trigger.yaml`（メタ情報）と `handler.sh`（処理本体）の2つが必要。

## trigger.yaml

```yaml
name: weather
description: "天気予報を取得する（例: weather 名古屋）"
handler: handler.sh
```

| フィールド | 必須 | 説明 |
|---|---|---|
| `name` | ◯ | ツール名。LLMがFunction Callingで指定する識別子 |
| `description` | ◯ | **LLMが「これを使うか」判断する手がかり**。具体例（例: `weather 名古屋`）を含めると判定精度が上がる |
| `handler` | ◯ | 実行するスクリプトのパス（`trigger.yaml` からの相対パス） |

## handler.sh

普通のシェルスクリプト。**ワークスペースルートをcwdとして実行される**。LLMが Function Calling で生成した引数が `$1`, `$2`, ... `$@` に入る。標準出力に書いたものがLLMに返る（LLMがそれを読んでユーザーに応答）。

```bash
#!/bin/bash
CITY="${1:-Tokyo}"
curl -s "wttr.in/${CITY}?format=3&lang=ja" 2>/dev/null \
  || echo "天気情報の取得に失敗しました"
```

ポイント:

- **shebang は `#!/bin/bash`** — `chmod +x` も忘れず（cloneしたままでも実行ビットは保持されている）
- **エラーは出力でユーザーに伝える** — チャットに返るのは標準出力なので、失敗時もユーザーに分かるメッセージを出す
- **引数のデフォルト値** — `${1:-Tokyo}` のように省略時の挙動を決めておく
- **長時間処理は `nohup` でバックグラウンド** — チャット側のタイムアウト（数分〜）を超えるなら、起動だけして「実行開始した」と返す

## 新しいトリガーの作り方

```bash
# 1. ディレクトリを作る
mkdir triggers/myhello

# 2. trigger.yaml を書く
cat > triggers/myhello/trigger.yaml <<'EOF'
name: myhello
description: "挨拶を返す"
handler: handler.sh
EOF

# 3. handler.sh を書く
cat > triggers/myhello/handler.sh <<'EOF'
#!/bin/bash
echo "こんにちは ${1:-世界} さん"
EOF
chmod +x triggers/myhello/handler.sh

# 4. xangi を再起動（新トリガーは起動時に読み込まれる）
xangi-cmd system_restart
```

登録後はチャットで「○○さんに挨拶して」のような自然言語で話しかけると、LLMが `myhello` トリガーを呼ぶ判断をして `こんにちは からあげ さん` のような応答を返してくれる（具体的な発火条件は `description` の書き方次第）。

## xangi 以外で使う場合

トリガーは単なるシェルスクリプトなので、xangi に縛られず単体でも使える。

```bash
./triggers/weather/handler.sh 名古屋
./triggers/rag/handler.sh "AI開発ワークフロー"
```

別のFunction Calling対応LLMフレームワークから呼ぶことも、CIから呼ぶことも可能。

## デバッグ

- LLMが呼んでくれない → `trigger.yaml` の `description` を見直す。具体例（`例:`〜）を含めると判定精度が上がる
- 認識されない → `trigger.yaml` の `name` と `handler` のパスを確認
- LLMが呼んでも失敗する → 直接 `bash triggers/<name>/handler.sh <args>` で実行して切り分け
- 出力が文字化け → ロケール設定（`LANG=ja_JP.UTF-8`）を確認

## 同梱されているトリガー

| トリガー | 説明 | LLMが呼ぶ場面の例 |
|---|---|---|
| [rag](rag/README.md) | ワークスペースRAGで検索（[`workspace-rag`](../skills/workspace-rag/) 連携） | 「過去のメモから○○探して」 |
| [technews](technews/README.md) | 最新テックニュース取得（RSS） | 「テックニュース教えて」 |
| [weather](weather/README.md) | 天気予報取得（wttr.in） | 「名古屋の天気は？」 |

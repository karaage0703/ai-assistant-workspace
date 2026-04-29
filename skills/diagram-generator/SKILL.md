---
name: xs:diagram-generator
description: 内容に応じて最適な図表形式を自動選択し、ローカルで画像生成（Pillow）またはコード出力（Mermaid/PlantUML）。フローチャート、アーキテクチャ図、階層図などを生成。資料作成、システム設計時に使用。
---

# スマート図表生成支援

内容に応じて最適な図表形式を自動選択し、画像を生成する。

## 判断フロー

```
Mermaidコードがすでにある？
  ├─ YES → Docker mermaid-cli で画像化（最優先）
  └─ NO  → 内容に応じて選択
              ├─ フロー/シーケンス → Mermaidコード作成 → Docker mermaid-cli
              └─ アーキテクチャ/階層 → Pillow（uv run）で直接生成
```

---

## 1. Mermaid → 画像化（Docker mermaid-cli）

**Mermaidコードがある場合はこれを最優先で使う。**

```bash
# 1. Mermaidファイルを作成
cat > /tmp/diagram.mmd << 'EOF'
flowchart TB
    A[開始] --> B[処理]
    B --> C{判断}
    C -->|Yes| D[完了]
    C -->|No| B
EOF

# 2. Docker版 mermaid-cli で画像生成
docker run --rm -u $(id -u):$(id -g) \
  -v /tmp:/data \
  minlag/mermaid-cli \
  -i /data/diagram.mmd -o /data/diagram.png -b white
```

**ポイント:**
- `-u $(id -u):$(id -g)` でパーミッション問題を回避
- `-b white` で白背景（スライド向け）
- 日本語・絵文字も表示可能
- SVG出力: `-o /data/diagram.svg`

### ⚠️ Mermaid記法の注意（よく間違えるやつ）

**改行は `<br>` を使う！ `\n` は使わない！**

```mermaid
# NG（\n がそのまま表示される）
A["Gateway\nRust / Axum"]

# OK（ちゃんと改行される）
A["Gateway<br>Rust / Axum"]
```

**subgraphのタイトルが長いと途中で改行される:**
- タイトルは短くする（15文字以内推奨）
- 補足は中のノードに書く

**線の交差を減らすコツ:**
- `direction LR` / `direction TB` をsubgraph内で使い分ける
- 関連するノードを近くに配置する
- 包含関係はsubgraphのネストで表現する（矢印より明確）

**subgraphのネスト例（包含関係の表現）:**
```mermaid
subgraph outer["親システム"]
    subgraph inner["子システム"]
        A["コンポーネントA"]
    end
    B["コンポーネントB"] --> A
end
```

### 複数ファイルを一括変換

```bash
for f in /tmp/*.mmd; do
  docker run --rm -u $(id -u):$(id -g) \
    -v /tmp:/data \
    minlag/mermaid-cli \
    -i /data/$(basename "$f") -o /data/$(basename "$f" .mmd).png -b white
done
```

---

## 2. Pillow で直接画像生成（uv run）

Mermaidを経由せず、直接画像を生成したい場合に使用。

### スクリプト実行

```bash
uv run --with pillow python [SKILL_DIR]/draw_diagram.py <type> -o <output.png> -d '<json>'
```

### 対応する図の種類

#### アーキテクチャ図 (`architecture`)

```bash
uv run --with pillow python [SKILL_DIR]/draw_diagram.py architecture \
  -o /tmp/arch.png -d '{
  "title": "システム構成",
  "boxes": [
    {"id": "api", "label": "API Server", "color": "blue", "row": 0, "col": 1},
    {"id": "db", "label": "Database", "sublabel": "PostgreSQL", "color": "green", "row": 1, "col": 0},
    {"id": "cache", "label": "Cache", "sublabel": "Redis", "color": "orange", "row": 1, "col": 2}
  ],
  "arrows": [
    {"from": "api", "to": "db", "label": "query"},
    {"from": "api", "to": "cache", "label": "read/write"}
  ]
}'
```

**パラメータ:**
- `boxes[].id`: 識別子（矢印の接続に使用）
- `boxes[].label`: メインラベル
- `boxes[].sublabel`: サブラベル（オプション）
- `boxes[].color`: blue/orange/purple/green/red/gray/teal
- `boxes[].row`, `boxes[].col`: グリッド位置
- `arrows[].from`, `arrows[].to`: 接続元・先の id
- `arrows[].label`: 矢印のラベル（オプション）

#### フローチャート (`flowchart`)

```bash
uv run --with pillow python [SKILL_DIR]/draw_diagram.py flowchart \
  -o /tmp/flow.png -d '{
  "title": "ユーザー登録フロー",
  "steps": [
    {"id": "s1", "label": "開始", "type": "start"},
    {"id": "s2", "label": "フォーム入力", "type": "process"},
    {"id": "s3", "label": "バリデーション", "type": "decision"},
    {"id": "s4", "label": "DB保存", "type": "process"},
    {"id": "s5", "label": "完了", "type": "end"}
  ],
  "connections": [
    {"from": "s1", "to": "s2"},
    {"from": "s2", "to": "s3"},
    {"from": "s3", "to": "s4", "label": "OK"},
    {"from": "s4", "to": "s5"}
  ]
}'
```

**ステップの type:** `start`（緑）/ `end`（赤）/ `process`（青）/ `decision`（オレンジ）

#### 階層図 (`hierarchy`)

```bash
uv run --with pillow python [SKILL_DIR]/draw_diagram.py hierarchy \
  -o /tmp/org.png -d '{
  "title": "組織図",
  "root": {
    "label": "CEO",
    "color": "purple",
    "children": [
      {"label": "CTO", "color": "blue", "children": [
        {"label": "Dev Team", "color": "green"},
        {"label": "Infra Team", "color": "green"}
      ]},
      {"label": "CFO", "color": "orange", "children": [
        {"label": "Finance", "color": "gray"}
      ]}
    ]
  }
}'
```

---

## 利用可能な色

| 色名 | 用途の目安 |
|------|-----------|
| `blue` | 技術系、API、サーバー |
| `green` | 正常系、開始、データベース |
| `orange` | 条件分岐、警告、キャッシュ |
| `purple` | 重要、トップレベル |
| `red` | 終了、エラー、削除 |
| `gray` | 補助、外部システム |
| `teal` | その他 |

---

## 使用例

### Mermaidコードを画像化したい場合
```
「このMermaidを画像にして」
→ .mmdファイルに保存 → docker mermaid-cli → PNG送信
```

### ゼロから図を作りたい場合
```
「APIサーバー、DB、キャッシュの構成図を作って」
→ Pillow architecture で JSON 生成 → uv run → PNG送信

「ユーザー登録の流れをフローチャートにして」
→ Mermaidコード作成 → docker mermaid-cli → PNG送信
```

---

## ⚠️ 注意事項

- **ローカル mermaid-cli (npx)**: ARM64環境ではPuppeteerが動作しないため非推奨。Docker版を使うこと。
- Mermaid記法の落とし穴は上の「⚠️ Mermaid記法の注意」セクションを参照

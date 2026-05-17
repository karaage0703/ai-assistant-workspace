# xangi-kaizen

AIアシスタント上で起きた事象（再投稿、cron が回らない、データ不整合、想定外の動作、エラー等）を「事象整理 → ログ調査 → 真因特定 → 横展開 → 修正・報告」の5フェーズで深掘りし、再発防止までやり切るスキル。

製造業の「なぜなぜ分析（5 Whys）」を LLM エージェントに「フェーズで縛って」やらせるための実用枠組みです。

## 何ができるか

- 発生した事象の調査・根本原因分析（なぜを最低3回掘る）
- 過去事例（KEDB = Known Error Database）を引いて、同パターンなら対策を再利用
- 横展開検索（同じパターンが他の場所で起きていないか網羅）
- 修正実装 + 教訓を AGENTS.md / MEMORY.md に集約

## 使い方

```
調査して
原因調べて
なぜなぜ分析して
再発防止策を立てて
xangi-kaizen でこの事象を調査して
```

詳細な手順は [SKILL.md](./SKILL.md) を参照。

## 設計の背景

LLM 単発の「なぜを5回繰り返して」はハルシネーション（それっぽい嘘）で終わりがちです。このスキルが効くのは以下の4つを構造で強制しているからです。

1. フェーズで縛る — 「ログ調査」を飛ばして「真因特定」に走るのを禁止。reasoning model 系で多段推論が走るのと同じ効果
2. ツールを持たせる — grep / git log / reflog / 履歴取得を agent loop で叩く。LLM の「思い込み」が証拠で潰される
3. KEDB（過去事例 DB）をフェーズ1で必ず引く — RAG 併用が RCA 精度を上げるという研究知見と一致。同じパターンなら対策の再利用が効く
4. 横展開を独立フェーズに切り出す — LLM は「直して終わり」になりがち。「他に同じ罠は？」を必ず通すと連鎖事故が減る

## 参考文献

LLM をエージェントとして使った Root Cause Analysis（RCA）の研究は 2023〜2025 で急速に増えており、本スキルの設計はこれらの知見と整合しています。

- Roy et al. ["Exploring LLM-based Agents for Root Cause Analysis"](https://arxiv.org/abs/2403.04123) (arXiv:2403.04123) — クラウド障害で ReAct エージェントが単発 LLM を上回ることを実証
- Chen et al. ["Automatic Root Cause Analysis via Large Language Models for Cloud Incidents"](https://arxiv.org/pdf/2305.15778) (arXiv:2305.15778) — 約 4 万件の実インシデントで RAG 併用が精度向上を示す
- ["Reasoning Language Models for Root Cause Analysis in 5G Wireless Networks"](https://arxiv.org/abs/2507.21974) (arXiv:2507.21974) — Qwen2.5-RCA-32B が pass@1 95.86%
- ["Towards LLM-based Root Cause Analysis of Hardware Design Failures"](https://arxiv.org/abs/2507.06512) (arXiv:2507.06512) — o3-mini が pass@5 で 100%
- ["TAMO: Fine-Grained Root Cause Analysis via Tool-Assisted LLM Agent"](https://arxiv.org/abs/2504.20462) (arXiv:2504.20462) — マルチモーダル観測データ + ツール呼びで深掘り

## 必要な依存

- 標準的な Unix ツール: `bash` / `grep` / `git`
- チャットプラットフォーム経由の場合: xangi（`xangi-cmd discord_history` 等）
- ノート保存に `xs:note-taking` スキルを利用

## トラブルシューティング

「なぜ」が浅いまま終わる:

- フェーズ3で「なぜ」が2段で止まっていないか確認する
- 「ここまで掘れば再発防止策が書ける」と思える深さに到達していないなら、もう一段掘り下げる

横展開で何も見つからない:

- 検索クエリが事象表面に寄りすぎている可能性。真因のパターン名（例: 「runtime state が git 管理されている」）で再検索
- `git ls-files | grep -iE "state|cache|last_check|cookie|credential|\.pid$"` のような汎用クエリも併用

過去事例ノートが見つからない:

- 初回運用ではノートゼロが普通。1件ずつ積み上がる
- ファイル名は `YYYYMMDD_xangi-kaizen_<事象タイトル>.md`、フロントマターに `tags: [xangi-kaizen, incident, <対象スキル名>]` を必ず付ける

## オリジナル / 参考

karaage の個人ワークスペース [borot](https://github.com/karaage0703/borot) で1ヶ月運用したスキル `xangi-kaizen` を、ai-assistant-workspace 向けに汎用化したものです。実運用での改善事例（content-digest 再投稿、borot master 誤コミット、pm2 restart rejected 誤解、Edit ツール並行上書き等）は borot の `notes/*_xangi-kaizen_*.md` を参照してください。

---
name: xs:xangi-kaizen
description: AIアシスタント上で起きた事象（再投稿・cronが回らない・データ不整合・想定外の動作・エラー等）の調査・根本原因分析（なぜなぜ分析）・横展開・修正・報告を、再現性のあるワークフローで実行する汎用スキル。トヨタ式 5 Whys を LLM エージェントに「フェーズで縛って」やらせる枠組み。「調査して」「原因調べて」「再発防止」「横展開して」「xangi-kaizen」「なぜなぜ分析」「事象を分析して」で発動。
---

# xangi-kaizen（なぜなぜ分析・根本原因分析スキル）

AIアシスタント上で起きた事象を「事象整理 → ログ調査 → 真因特定 → 横展開 → 修正・報告」の5フェーズで深掘りし、再発防止までやり切る汎用スキル。

スキルの背景・設計思想・参考文献は [README.md](./README.md) を参照。

## 3原則

1. **フェーズを飛ばさない** — 「事象整理」を飛ばすと検証ポイントを見失う。「横展開」を飛ばすと同じ事故を別箇所で繰り返す
2. **想定で終わらせず証拠で詰める** — 「たぶん」を提出物にしない。仮説 → 証拠（履歴出力・ファイル中身・git log・mtime 等） → 検証
3. **真因が特定できるまで実装に進まない** — 表面的な対症療法は再発の温床

## 5フェーズのワークフロー

### Phase 1: 事象の整理（既知問題チェック含む）

何が起きた / いつ / どこで（チャンネル・対象スキル・対象ファイル）。事実を時系列で整理する。

ステップ:

1. 関連する会話履歴・ログを取得して事象の輪郭をつかむ
   - チャットプラットフォーム（Discord/Slack 等）で xangi 経由なら:
     ```bash
     xangi-cmd discord_history --count 30
     xangi-cmd discord_history --channel <ID> --count 50
     ```
   - ローカル CLI なら該当アプリのログ・出力を確認
2. 関係するスキル名・cron スケジュール・関連ファイルを箇条書きで把握する
3. 過去事例（KEDB = Known Error Database）を必ず確認 — `[NOTES_DIR]` の過去 xangi-kaizen ノートを事象キーワードで grep
   ```bash
   # xangi-kaizen タグの全事例
   grep -rl '#xangi-kaizen' [NOTES_DIR] | sort

   # 対象スキル名・キーワードで絞り込み
   grep -rl '#<対象スキル名>' [NOTES_DIR]
   grep -rl 'state\|cron\|<キーワード>' [NOTES_DIR]/*xangi-kaizen* 2>/dev/null
   ```
   ヒットした事例は中身を読む。同じパターンなら「対策」「教訓」をそのまま適用できる。未知なら次フェーズへ。

### Phase 2: ログ調査

複数のソースを横断的に追う。一つの観点で結論を出さない。

| 観点 | コマンド/対象 |
|------|--------------|
| state ファイル | `[STATE_DIR]/*_state.json`、`*_last_check.json` 等の中身と `stat -c "%y %n"` |
| git 履歴 | `git log -p --all -- <path>`、`git show <commit>:<path>` |
| git reflog | `git reflog --since=<時刻>`（ブランチ切替・rebase・reset の追跡） |
| cron / schedule | `xangi-cmd schedule_list 2>&1 \| grep -B2 -A3 <キーワード>`、または cron 実体 |
| セッションログ | `[WORKSPACE]/logs/sessions/*.jsonl` 等のランタイムログ |
| 該当スクリプト | `[SKILLS_DIR]<name>/scripts/`（差分検出ロジックの確認） |
| 会話履歴 | `xangi-cmd discord_history --channel <ID> --count 30` |

「これしか見ていない」状態で次フェーズに行かない。

### Phase 3: 真因特定（なぜなぜ分析の本体）

**「なぜ」を最低3回掘る。** 誰が読んでも納得できる説明になるまで掘り続ける。

仮説 → 証拠 → 検証のサイクル。仮説が間違ってたら戻る。実装前に詰める。

例:

- 仮説1: cron が動いてなかった → 投稿履歴で確認 → ✗（cron は動いてた）
- 仮説2: state がロールバックされた → reflog で `pull --rebase` / `checkout` 多発を確認 → ✓
- なぜロールバックした？ → state が git 管理されてた + 開発作業の git 操作頻発 → ✓
- なぜ state が git 管理されてた？ → 新規追加時に `.gitignore` を更新する規約が無かった → ✓（真因）

「ここまで掘れば再発防止策が書ける」と思える深さまで掘る。一段で止まると対症療法になる。

### Phase 4: 横展開

同じパターンの他ファイル/問題を網羅検索する。1件直しても、別の場所で同じ事故が起きうる。

```bash
# ランタイム状態ファイル系を全部洗い出し
git ls-files | grep -iE "state|cache|last_check|cookie|credential|\.pid$"

# 巨大ログ系（リポジトリ肥大化のリスク）
git ls-files | xargs -I {} stat -c "%s %n" {} 2>/dev/null | sort -rn | head -20

# 最近書き換えられた tracked ファイル（書き換え頻度 + tracked = 罠）
git ls-files | xargs -I {} stat -c "%y %n" {} 2>/dev/null | sort -r | head -30
```

事象の根本パターンに沿って検索クエリを組み立てる。「state ファイルが git ロールバックされた」が真因なら「他に git 管理されてる runtime state は無いか」を網羅する。

### Phase 5: 修正実装と報告

実装方針:

- 自分管理のリポ（個人運用）→ 直 push でも可
- 他者・チームと共有しているリポ → PR フロー
- ランタイム state / cache / log は **絶対に git 管理しない**（`.gitignore` に追加）

報告フォーマット:

- 背景 — 何が起きたか（時系列）
- 原因 — なぜ起きたか（証拠付き、なぜを3段以上）
- 対策 — 何をしたか（変更ファイル・コミット・PR）
- テスト結果 — 動作確認の証拠（コマンド出力・履歴）
- 残課題 — 横展開で保留したもの・観察期間が必要なもの

## 調査結果の保存

詳細レポートは `[NOTES_DIR]` にタグ付きで保存する。事例は積み重ねていく（次回の調査で Phase 1 の KEDB として効く）。

- ファイル名: `[NOTES_DIR]YYYYMMDD_xangi-kaizen_<事象タイトル>.md`
- フロントマター:
  ```yaml
  ---
  title: <事象タイトル>
  date: YYYY-MM-DD
  type: incident
  tags:
    - xangi-kaizen
    - incident
    - <対象スキル名>
  ---
  ```
- 保存は `xs:note-taking` スキルに従う（命名規則・フロントマター・同期手順を活用）

過去事例を参照したいときは:

```bash
grep -rl '#xangi-kaizen' [NOTES_DIR] | sort
```

横展開で見つかったパターン化された教訓は、次回の調査ですぐ参照したいので `[WORKSPACE]/AGENTS.md` または `[WORKSPACE]/MEMORY.md` の長期記憶セクションに集約する。

## 使用例

```
xs:xangi-kaizen
xangi-kaizen でこの事象を調査して
原因調べて
なぜなぜ分析して
再発防止策を立てて
調査して、横展開もしてほしい
事象を分析して
```

---
name: xs:xangi-kaizen
description: xangi 上で起きた事象（再投稿・cron が回らない・データ不整合・想定外の動作・エラー等）の調査・根本原因分析・横展開・修正・報告を、再現性のあるワークフローで実行する汎用スキル。「調査して」「原因調べて」「再発防止」「横展開して」「xangi-kaizen」「事象を分析して」で発動。
---

# xangi-kaizen

xangi 上で起きた事象を「事象整理 → ログ調査 → 真因特定 → 横展開 → 修正・報告」の5フェーズで深掘りし、再発防止までやり切る汎用スキル。

スキルの背景・設計思想・参考文献は [README.md](./README.md) を参照。

## 3原則

1. **フェーズを飛ばさない** — 「事象整理」を飛ばすと検証ポイントを見失う。「横展開」を飛ばすと同じ事故を別箇所で繰り返す
2. **想定で終わらせず証拠で詰める** — 「たぶん」を提出物にしない。仮説 → 証拠（git log / reflog / mtime / 履歴出力） → 検証
3. **真因が特定できるまで実装に進まない** — 表面的な対症療法は再発の温床
4. **コードで推測する前に、事象が出た実際のターンのログを必ず開く** — とくに「変な応答が返った」「空だった」「想定と違う出力」系。コードを読んで fallback を見つけると「原因はこれ」と早合点しがちだが、それは「どこで出るか」であって「そのターンで実際に何が起きたか」ではない。先に Phase 2 で対象 bot の session log / tool-trajectory を開き、そのターンの生データを確定してから、コードで「なぜそうなったか」を辿る。

## 5フェーズのワークフロー

### Phase 1: 事象の整理（既知問題チェック含む）

何が起きた / いつ / どこで（チャンネル・対象スキル）。事実を時系列で整理する。

**ステップ:**

1. 引用メッセージ・チャンネル履歴を取得して事象の輪郭をつかむ
   ```bash
   xangi-cmd discord_history --count 30
   xangi-cmd discord_history --channel <ID> --count 50
   ```
2. 関係するスキル名・cron スケジュール・関連ファイルを箇条書きで把握する
3. **過去事例（KEDB = Known Error Database）を必ず確認** — `[NOTES_DIR]` の過去 xangi-kaizen ノートを事象キーワードで grep
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

**ステップ 0（重要）: 調査対象 bot の workspace を特定する。** xangi は bot ごとに別 workspace・別プロセスで動く構成を取りうる。複数 bot を運用している場合、手元の workspace だけを見ても対象 bot の事象は写っていないことがある。

```bash
# Docker 運用の場合: bot がどのコンテナか確認
docker ps --format '{{.Names}}\t{{.Image}}'

# コンテナの workspace マウント元を確認
docker inspect <container> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' | grep '/workspace'
```

特定した `<bot-workspace>` 配下の `logs/sessions/` と `logs/tool-trajectory/` を見る。環境変数やチャンネル割り当ては各 bot の `.env` で確認する。

| 観点 | コマンド/対象 |
|------|--------------|
| state ファイル | `[STATE_DIR]/*_state.json`、`references/*_last_check.json` 等の中身と `stat -c "%y %n"` |
| git 履歴 | `git log -p --all -- <path>`、`git show <commit>:<path>` |
| git reflog | `git reflog --since=<時刻>`（ブランチ切替・rebase・reset の追跡） |
| cron / schedule | `xangi-cmd schedule_list 2>&1 \| grep -B2 -A3 <キーワード>` |
| セッションログ（生応答） | 対象 bot の `<bot-workspace>/logs/sessions/*.jsonl`。事象の出たチャンネル ID で `grep -rl <channelId>` → 該当ファイルの当該ターンを開き、assistant result を確認 |
| tool-trajectory ログ | `<bot-workspace>/logs/tool-trajectory/*.jsonl`。tool search / loop / drift / stream buffer / cache などのイベントが時系列で残る |
| 該当スクリプト/コード | `skills/<name>/scripts/`、または対象リポのソース。ログで事象を確定した後に「なぜそうなるか」を辿る |
| 投稿履歴 | `xangi-cmd discord_history --channel <ID> --count 30` |

「これしか見ていない」状態で次フェーズに行かない。

### Phase 3: 真因特定

**「なぜ」を最低3回掘る。** 誰が読んでも納得できる説明になるまで掘り続ける。

仮説 → 証拠 → 検証のサイクル。仮説が間違ってたら戻る。実装前に詰める。

例:

- 仮説1: cron が動いてなかった → 投稿履歴で確認 → ✗（cron は動いてた）
- 仮説2: state がロールバックされた → reflog で `pull --rebase` / `checkout` 多発を確認 → ✓
- なぜロールバックした？ → state が git 管理されてた + 開発作業の git 操作頻発 → ✓

「ここまで掘れば再発防止策が書ける」と思える深さまで掘る。一段で止まると対症療法になる。

応答内容系（変な出力・空・drift）はコードからの推測で終わらせない。「コードのこの fallback だ」で止めず、Phase 2 で開いた当該ターンの生ログと突き合わせて確定する。ログで確定するまでは報告に「ここは未確認の推測」と明示する。

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

- 個人運用の自分管理リポ → 直 push でも可
- 他者・チームと共有しているリポ / 公開テンプレートリポ → PR フロー
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

横展開で見つかったパターン化された教訓は、次回の調査ですぐ参照したいので `[WORKSPACE]/AGENTS.md`、`[WORKSPACE]/MEMORY.md`、または `knowledge/lessons_archive.md` のような長期参照先に集約する。

## 使用例

```
xs:xangi-kaizen
xangi-kaizen でこの事象を調査して
原因調べて
再発防止策を立てて
調査して、横展開もしてほしい
事象を分析して
```

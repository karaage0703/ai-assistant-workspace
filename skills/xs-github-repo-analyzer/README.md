# xs-github-repo-analyzer

GitHubの現行HEADを基準に、DeepWikiの索引commitとの違いを確認してリポジトリを分析します。

## 使い方

「owner/repoを分析して」

## 必要なもの

認証・閲覧権限のあるgh CLI。DeepWikiは公開リポジトリに対する任意のWeb取得。

## 失敗時の扱い

DeepWikiが古い・未索引・取得不可でも、GitHubの現行コードから分析します。GitHubを取得できない場合は現行確認できない範囲を明記します。

具体的な手順・出力例は[SKILL.md](./SKILL.md)を参照してください。

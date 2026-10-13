# Cloudflare Workers を使った ES 寄り付き予測の予備スケジューラー

GitHub Actions の schedule が予定どおり起動しない場合の **独立した予備起動元** です。
Cloudflare Cron は Github の workflow_dispatch API を呼ぶだけで、株価を外部へ送信せず、
GitHub の既存 Python モデル・採点・履歴保存・Pages 公開をそのまま使います。

> 注意：GitHub Actions を外部から起動しても、GitHub 側の実行待ちや失敗があるので
> 時刻の完全保証はありません。**Cloudflare の Worker をデプロイし Cron と Secret を設定してから**運用開始です。
> GitHub リポジトリにこれらのファイルを追加しただけではバックアップは動きません。

## まず用意するもの
- 既存の Cloudflare アカウント
- 対象 GitHub リポジトリ：`soan4/es-open-signal`
- GitHub Fine-grained Personal Access Token (PAT) — **このチャットやソースコードに貼らないこと**
  - Repository access: **Only select repositories** → `soan4/es-open-signal`
  - Repository permissions → **Actions: Read and write**（Contentsは既存 Actions の GITHUB_TOKEN を使うため不要）
  - 期限を設定し、期限切れ前に更新する
  - 公式作成先: https://github.com/settings/personal-access-tokens/new

## 方法A：iPhoneの Cloudflare ダッシュボード
1. https://dash.cloudflare.com/ → **Workers & Pages → Create → Worker** で Worker を新規作成。
2. Worker のコードを `cloudflare-backup/src/index.mjs` の全文で置き換え、**Deploy**。
3. Worker → **Settings → Variables and Secrets → Add** で
   - Type: **Secret**
   - Name: `GITHUB_ACTIONS_TOKEN`
   - Value: 上で発行した Fine-grained PAT
   保存して再デプロイ。
4. Worker の **Settings → Triggers → Cron Triggers**（UI名称は変更の可能性あり）で、
   以下の UTC cron を追加：
   - `*/5 13-16 * * 1-5`
   - `15 20-22 * * 1-5`
   - `15 13-16 * * 6`
5. Worker → **Logs / Observability** で `External trigger` の結果を確認。
   `dispatched` = GitHub 起動要求成功、`already-predicted` = 既に自動予測済み、
   `already-graded` = 既に自動採点済み。`dispatch-failed` は PAT の権限・期限を確認。

## 方法B：PCから Wrangler を使う
```bash
cd cloudflare-backup
npx wrangler login
npx wrangler secret put GITHUB_ACTIONS_TOKEN
npx wrangler deploy
```
`wrangler.jsonc` の crons がデプロイに反映されます。

## UTCと米東部時間
Cloudflare Cron は UTC です。夏時間 09:20 ET = 13:20 UTC、冬時間 09:20 ET = 14:20 UTC。
コード内部で America/New_York に変換し、週末と予測開始・終了時刻を確認。
* preopen 09:10, 09:15, 09:20, 09:25 ET
* 採点 10:10, 10:30, 10:50, 11:15 ET
* 再照合 16:15 ET
* 土曜日 10:15/11:15 ET に遅れ分を再照合

**予測は NYSE 09:30 まで**。後から生成することはありません。
手動・外部 `workflow_dispatch` の早期実行は 09:18 ET まで待機します。

## セキュリティ
- PAT は Secret に保存し、GitHub コミット、README、iPhone アプリ、ChatGPT には貼らない。
- Worker の公開 HTTP URL は読取専用。ブラウザ GET でGitHubを起動できない設計。
- GitHub workflow は既存の `GITHUB_TOKEN` でデータを更新する。
- PAT の期限切れ・失効に注意。期限が近付けばローテーションが必要。
- 不要になれば Cloudflare Worker を削除し GitHub 側 PAT を失効させる。

## トラブル時
- Workerの `dispatched` は「起動のAPI要求」が成功しただけ。GitHub Actionsの
  `ES signal and iPhone site` が成功し、`data/latest.json` と
  `data/shadow.json` が当日になったことを確認。
- GitHub が起動してもデータ提供元のYahooに接続できなければ判定保留になる。
- Worker自体のCronも絶対に遅延なしとは限らない。
- 最初の米国営業日に少なくとも1回、`External trigger` と GitHub Actions の履歴を確認する。

# War Thunder News → Discord

DMM日本語公式サイトとGaijin英語公式サイトの新着記事を定期確認し、同じDiscordチャンネルへWebhook通知するGitHub Actions用プログラムです。

## 動作仕様

- 指定時間ごとに監視（GitHub Actionsの都合で実行時刻は前後します）
- 対象:
  - https://warthunder.dmm.com/
  - https://warthunder.com/en/news
- 新着記事を検出するとDiscordへ通知
- 日本語版と英語版は独立扱い。同じ内容でも両方通知
- 初回実行では現在の記事一覧を基準として保存し、通知しない
- 自宅PCの常時起動は不要

## セットアップ

1. GitHubで新しいPublicまたはPrivateリポジトリを作成する。
2. このフォルダ内のファイルをリポジトリの同じ階層構成でアップロードする。
3. Discordの通知先チャンネルでWebhookを作成し、Webhook URLをコピーする。
4. GitHubリポジトリの `Settings` → `Secrets and variables` → `Actions` → `New repository secret` を開く。
5. Nameに `DISCORD_WEBHOOK_URL`、SecretにコピーしたWebhook URLを設定する。
6. `Actions` タブで `War Thunder news monitor` を選び、`Run workflow` を押して初回実行する。
7. 初回実行が成功したら、以後10分間隔の自動監視が有効になる。

## 注意

- WebサイトのHTML構造が変わると、記事の検出ロジックを調整する必要があります。
- 初回実行は既存記事を通知せず、以後に一覧に現れた記事を通知します。
- サイトへのアクセス失敗時はGitHub Actionsのログにエラーを記録します。
- Webhook URLはパスワード同様の秘密情報です。コードや公開リポジトリに直接書かず、必ずGitHub Secretsに登録してください。
- GitHub Actionsのスケジュール実行は混雑等により遅延する場合があります。
- これはページ内のリンクを抽出する汎用方式です。サイト側の表示方式によっては初回テスト後にセレクタ調整が必要です。

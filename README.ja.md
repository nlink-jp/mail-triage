# mail-triage

GCS上のメールファイルをGemini LLMで分類・分析し、結果をSlackに通知するツール。
Google Cloud Run Jobとして動作し、EventarcトリガーおよびCloud Schedulerによる定期実行に対応。

## 機能

- `.eml`（RFC 2822）および `.msg`（OLE2/MAPI）形式のメールをGCSから解析
- Gemini LLMによるメール分析（カテゴリ・優先度・要約・タグ・言語検出）
- Slack Block Kit形式の通知投稿
- 2つの実行モード:
  - **単一ファイル** (`--file`): EventarcによるGCSオブジェクト作成トリガー
  - **スイープ** (デフォルト): 未処理ファイルの一括処理、Cloud Schedulerトリガー
- サマリ内のURL/ドメインを自動デファング（誤クリック防止）
- ノンスタグXMLラッピングによるプロンプトインジェクション防御
- LLM一時エラーに対する指数バックオフリトライ

## インストール

```bash
# クローン
git clone https://github.com/nlink-jp/mail-triage.git
cd mail-triage

# 依存関係のインストール
uv sync
```

## 設定

すべての設定は `MAIL_TRIAGE_` プレフィックス付きの環境変数、またはCLIフラグで指定。

| 環境変数 | フラグ | デフォルト | 説明 |
|----------|--------|-----------|------|
| `MAIL_TRIAGE_BUCKET` | `--bucket` | (必須) | GCSバケット名 |
| `MAIL_TRIAGE_PREFIX` | `--prefix` | `inbox/` | 入力プレフィックス |
| `MAIL_TRIAGE_DONE_PREFIX` | `--done-prefix` | `processed/` | 処理済みプレフィックス |
| `MAIL_TRIAGE_PROJECT` | `--project` | (必須) | GCPプロジェクトID |
| `MAIL_TRIAGE_LOCATION` | `--location` | `us-central1` | Vertex AIリージョン |
| `MAIL_TRIAGE_MODEL` | `--model` | `gemini-2.5-flash` | Geminiモデル名 |
| `SUMMARY_LANG` | `--summary-lang` | (自動検出) | サマリ言語の強制指定 |
| `SLACK_BOT_TOKEN` | `--slack-token` | | Slackボットトークン |
| `SLACK_CHANNEL` | `--slack-channel` | | 投稿先Slackチャンネル |

## 使い方

### ローカル実行

```bash
# 認証設定
gcloud auth application-default login

# スイープモード（未処理ファイルを一括処理）
uv run mail-triage --bucket my-bucket --project my-project --slack-channel '#mail-digest'

# 単一ファイルモード
uv run mail-triage --bucket my-bucket --project my-project --file inbox/alert.eml

# ドライラン（投稿・移動なしで解析のみ）
uv run mail-triage --bucket my-bucket --project my-project --dry-run
```

### Cloud Run Jobデプロイ

`deploy.sh` によるワンライナーデプロイ:

```bash
# 1. 設定ファイルをコピー・編集
cp deploy/deploy.env.template deploy/deploy.env
# deploy/deploy.env を編集

# 2. デプロイ実行
./deploy/deploy.sh deploy/deploy.env

# 3. SlackボットトークンをSecret Managerに登録
echo -n 'YOUR_SLACK_BOT_TOKEN' | gcloud secrets versions add mail-triage-slack-bot-token \
  --data-file=- --project=PROJECT_ID
```

`deploy.sh` が構築するリソース:
- GCSバケット
- Artifact Registryリポジトリ
- 必要なIAMロールを持つサービスアカウント
- 環境変数とシークレットを設定したCloud Run Job
- Eventarcトリガー（GCSオブジェクト作成 → ジョブ実行）
- Cloud Scheduler（定期スイープ）

### アーキテクチャ

```
┌──────────────┐  object.finalize  ┌──────────────────┐
│ GCS          │──── Eventarc ────▶│ Cloud Run Job     │ ← 単一ファイルモード
│ (inbox/)     │                   │ (mail-triage)   │
└──────────────┘                   └──────┬───────────┘
                                          │
┌──────────────┐  cron (フォールバック)     │
│ Cloud        │──── trigger ────▶ 同一ジョブ（スイープモード）
│ Scheduler    │                          │
└──────────────┘                   ┌──────┼──────┐
                                   ▼      ▼      ▼
                                  GCS  Gemini  Slack
```

## メール分析

メールは以下のカテゴリに分類:

| カテゴリ | 絵文字 |
|---------|--------|
| security-alert | :rotating_light: |
| incident | :fire: |
| vulnerability | :warning: |
| compliance | :shield: |
| threat-intel | :mag: |
| newsletter | :newspaper: |
| announcement | :loudspeaker: |
| discussion | :speech_balloon: |
| other | :email: |

優先度: **high** (:red_circle:)、**medium** (:large_orange_circle:)、**low** (:white_circle:)

## ビルド

```bash
make test    # テスト実行
make lint    # リントチェック
make build   # dist/ にホイールをビルド
```

## 必要なAPI権限

| サービス | 権限 |
|---------|------|
| GCS | `storage.objects.list`, `get`, `create`, `delete` |
| Vertex AI | `aiplatform.endpoints.predict` |
| Slack | Botスコープ: `chat:write`, `files:write` |
| Secret Manager | `secretmanager.versions.access` |

## ドキュメント

- [README.md](README.md)（English）
- [README.ja.md](README.ja.md)（日本語）
- [Architecture](docs/architecture.md)（設計判断と内部構造）
- [How to Setup](docs/setup.md)（GCP / Slack prerequisites）
- [How to Setup (ja)](docs/setup.ja.md)（GCP / Slack 事前準備）
- [CHANGELOG.md](CHANGELOG.md)

# How to Setup — mail-triage

mail-triage のデプロイに必要な GCP と Slack の事前準備手順です。
`deploy.sh` を実行する前にこのドキュメントの手順をすべて完了してください。

---

## 目次

1. [前提条件](#前提条件)
2. [GCP の事前準備](#gcp-の事前準備)
3. [Slack の事前準備](#slack-の事前準備)
4. [デプロイ設定ファイルの作成](#デプロイ設定ファイルの作成)
5. [デプロイの実行](#デプロイの実行)
6. [動作確認](#動作確認)
7. [トラブルシューティング](#トラブルシューティング)

---

## 前提条件

ローカルマシンに以下がインストールされていること:

| ツール | 確認コマンド | インストール |
|--------|-------------|-------------|
| Google Cloud CLI | `gcloud version` | https://cloud.google.com/sdk/docs/install |
| Docker | `docker version` | https://docs.docker.com/get-docker/ |
| uv (ローカル開発時) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

---

## GCP の事前準備

### 1. GCP プロジェクトの作成または選択

既存のプロジェクトを使うか、新規に作成します。

```bash
# 新規作成の場合
gcloud projects create PROJECT_ID --name="Mail Triage"

# 既存プロジェクトを選択
gcloud config set project PROJECT_ID
```

> **注意**: `PROJECT_ID` はグローバルに一意である必要があります。

### 2. 課金の有効化

Cloud Run、Vertex AI、Cloud Storage はすべて課金が必要です。

```bash
# 課金アカウントの確認
gcloud billing accounts list

# プロジェクトに課金アカウントを紐づけ
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
```

または [Cloud Console](https://console.cloud.google.com/billing) から設定してください。

### 3. 必要な API の有効化

`deploy.sh` が自動で有効化しますが、事前に手動で確認する場合:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  eventarc.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  --project=PROJECT_ID
```

| API | 用途 |
|-----|------|
| Cloud Run | ジョブの実行 |
| Artifact Registry | コンテナイメージの保存 |
| Eventarc | GCS イベントトリガー |
| Cloud Scheduler | 定期スイープ |
| Cloud Storage | メールファイルの保存 |
| Vertex AI | Gemini LLM による分析 |
| Secret Manager | Slack トークンの安全な保存 |

### 4. Vertex AI のリージョン確認

Gemini モデルが利用可能なリージョンを使用してください。
`gemini-2.5-flash` は以下のリージョンで利用可能です:

- `us-central1` (推奨)
- `europe-west1`
- `asia-northeast1` (東京)

```bash
# リージョンを設定
gcloud config set run/region us-central1
```

### 5. ローカル開発用の認証設定

ローカルでテスト実行する場合に必要です（デプロイのみなら不要）。

```bash
# ADC (Application Default Credentials) の設定
gcloud auth application-default login

# Docker の認証設定（deploy.sh が自動実行しますが事前でも可）
gcloud auth configure-docker REGION-docker.pkg.dev
```

### 6. gcloud CLI のアカウント確認

`deploy.sh` を実行するアカウントに以下の権限があることを確認:

- **プロジェクトオーナー** または **編集者** (推奨: 初回セットアップ時)
- 最低限必要な個別ロール:
  - `roles/iam.serviceAccountAdmin` — SA 作成
  - `roles/resourcemanager.projectIamAdmin` — IAM バインディング
  - `roles/storage.admin` — バケット作成
  - `roles/artifactregistry.admin` — リポジトリ作成
  - `roles/run.admin` — Cloud Run Job 作成
  - `roles/eventarc.admin` — トリガー作成
  - `roles/cloudscheduler.admin` — スケジューラ作成
  - `roles/secretmanager.admin` — シークレット作成

```bash
# 現在の認証アカウントを確認
gcloud auth list
```

---

## Slack の事前準備

### 1. Slack App の作成

1. [Slack API: Your Apps](https://api.slack.com/apps) にアクセス
2. **Create New App** → **From scratch** を選択
3. App Name: `mail-triage`（任意）
4. Workspace: 投稿先のワークスペースを選択
5. **Create App** をクリック

### 2. Bot Token Scopes の設定

1. 左メニューの **OAuth & Permissions** を開く
2. **Scopes** セクションの **Bot Token Scopes** で以下を追加:

| Scope | 用途 |
|-------|------|
| `chat:write` | チャンネルへのメッセージ投稿 |
| `files:write` | スレッドへのファイル添付（メール本文） |

> **注意**: `files:read` は不要です。アップロードのみ行います。

### 3. App のインストール

1. **OAuth & Permissions** ページ上部の **Install to Workspace** をクリック
2. 権限を確認して **Allow** をクリック
3. 表示される **Bot User OAuth Token** (`xoxb-` から始まる文字列) をコピー

> このトークンは後で Secret Manager に登録します。安全な場所に一時保管してください。

### 4. Bot をチャンネルに招待

投稿先のチャンネルに Bot を追加します:

```
# Slack のチャンネルで以下を入力
/invite @mail-triage
```

または:
1. チャンネル設定 → **Integrations** → **Apps** → **Add apps**
2. `mail-triage` を検索して追加

> Bot が招待されていないチャンネルには投稿できません（`not_in_channel` エラー）。

### 5. チャンネル ID の確認（オプション）

`SLACK_CHANNEL` にはチャンネル名（`#mail-digest`）またはチャンネル ID（`C01XXXXXXXX`）を指定できます。
チャンネル ID を使う方が確実です。

確認方法:
1. Slack でチャンネルを開く
2. チャンネル名をクリック → 最下部に **Channel ID** が表示される

---

## デプロイ設定ファイルの作成

```bash
cd mail-triage
cp deploy/deploy.env.template deploy/deploy.env
```

`deploy/deploy.env` を編集:

```bash
# ── 必須 ──
PROJECT_ID=your-gcp-project-id      # GCP プロジェクト ID
REGION=us-central1                   # Cloud Run / Vertex AI リージョン
BUCKET_NAME=your-mail-triage-bucket  # メールファイル格納用 GCS バケット名
SLACK_CHANNEL=#mail-digest           # Slack 通知先チャンネル

# ── 任意（デフォルト値あり） ──
# SCHEDULER_CRON="*/30 * * * *"      # スイープ間隔（デフォルト: 30分毎）
# SCHEDULER_TZ=Asia/Tokyo            # タイムゾーン
# SUMMARY_LANG=ja                    # サマリ言語の強制指定
# GEMINI_MODEL=gemini-2.5-flash      # Gemini モデル名
# JOB_TIMEOUT=600                    # ジョブタイムアウト（秒）
# JOB_MEMORY=512Mi                   # メモリ上限
```

> **重要**: `deploy/deploy.env` は `.gitignore` に含まれています。絶対にコミットしないでください。

---

## デプロイの実行

```bash
# 1. デプロイ（全リソースをまとめて構築）
./deploy/deploy.sh deploy/deploy.env

# 2. Slack Bot トークンを Secret Manager に登録
echo -n 'YOUR_SLACK_BOT_TOKEN' | \
  gcloud secrets versions add mail-triage-slack-bot-token \
    --data-file=- --project=PROJECT_ID
```

`deploy.sh` が作成するリソース:

| リソース | 名前 |
|---------|------|
| サービスアカウント | `mail-triage-sa@PROJECT_ID.iam.gserviceaccount.com` |
| GCS バケット | `gs://BUCKET_NAME` |
| Artifact Registry | `REGION-docker.pkg.dev/PROJECT_ID/mail-triage/` |
| Cloud Run Job | `mail-triage` |
| Eventarc トリガー | `mail-triage-gcs-trigger` |
| Cloud Scheduler | `mail-triage-sweep` |
| Secret | `mail-triage-slack-bot-token` |

---

## 動作確認

### テストメールのアップロード

```bash
# .eml ファイルをバケットの inbox/ にアップロード
gcloud storage cp test.eml gs://BUCKET_NAME/inbox/

# Eventarc トリガーにより自動的にジョブが起動される
# 数秒〜数十秒で Slack にメッセージが届く
```

### ジョブ実行状況の確認

```bash
# 最新の実行一覧
gcloud run jobs executions list \
  --job=mail-triage \
  --region=REGION \
  --project=PROJECT_ID

# 特定の実行のログ
gcloud run jobs executions logs EXECUTION_NAME \
  --job=mail-triage \
  --region=REGION \
  --project=PROJECT_ID
```

### 手動でスイープ実行

```bash
gcloud run jobs execute mail-triage \
  --region=REGION \
  --project=PROJECT_ID
```

### 処理済みファイルの確認

```bash
# inbox/ から processed/ に移動されていることを確認
gcloud storage ls gs://BUCKET_NAME/inbox/
gcloud storage ls gs://BUCKET_NAME/processed/
```

---

## トラブルシューティング

### Slack 関連

| エラー | 原因 | 対処 |
|--------|------|------|
| `not_in_channel` | Bot がチャンネルに招待されていない | `/invite @mail-triage` でチャンネルに追加 |
| `invalid_auth` | トークンが無効または未設定 | Secret Manager のトークン値を確認 |
| `channel_not_found` | チャンネル名/ID が間違っている | チャンネル ID（`C01XXX`）を直接指定する |
| `missing_scope` | 必要な scope が不足 | Slack App の OAuth & Permissions で scope を追加し、再インストール |
| `ratelimited` | API レート制限 | 自動リトライされるが、大量処理時は `SCHEDULER_CRON` の間隔を広げる |

### Gemini 関連

| エラー | 原因 | 対処 |
|--------|------|------|
| `PERMISSION_DENIED` | Vertex AI API が未有効または SA に権限なし | `gcloud services enable aiplatform.googleapis.com` + IAM 確認 |
| `RESOURCE_EXHAUSTED` / 429 | クォータ超過 | 自動リトライ（最大6回）。頻発する場合はクォータ引き上げを申請 |
| `NOT_FOUND` | モデル名またはリージョンが無効 | `GEMINI_MODEL` と `REGION` を確認 |

### GCS 関連

| エラー | 原因 | 対処 |
|--------|------|------|
| `403 Forbidden` | SA にバケットへのアクセス権がない | `roles/storage.objectAdmin` が付与されているか確認 |
| `404 Not Found` | バケットまたはオブジェクトが存在しない | バケット名とプレフィックスを確認 |

### Eventarc 関連

| エラー | 原因 | 対処 |
|--------|------|------|
| トリガーが発火しない | GCS サービスアカウントに `pubsub.publisher` ロールがない | `deploy.sh` が設定するが、手動確認: `gcloud projects get-iam-policy PROJECT_ID` |
| 重複実行 | Eventarc + Scheduler の両方が同じファイルを処理 | 正常動作（Eventarc が先に処理 → Scheduler は空振り） |

### 共通

```bash
# Cloud Run Job のログを確認
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=mail-triage" \
  --project=PROJECT_ID \
  --limit=50 \
  --format="table(timestamp,textPayload)"
```

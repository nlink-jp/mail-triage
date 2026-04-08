# How to Setup — mail-triage

Prerequisites for deploying mail-triage on GCP with Slack integration.
Complete all steps in this document before running `deploy.sh`.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [GCP Setup](#gcp-setup)
3. [Slack Setup](#slack-setup)
4. [Create Deploy Configuration](#create-deploy-configuration)
5. [Run Deployment](#run-deployment)
6. [Verification](#verification)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

The following tools must be installed on your local machine:

| Tool | Verify | Install |
|------|--------|---------|
| Google Cloud CLI | `gcloud version` | https://cloud.google.com/sdk/docs/install |
| Docker | `docker version` | https://docs.docker.com/get-docker/ |
| uv (local dev only) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

---

## GCP Setup

### 1. Create or Select a GCP Project

Use an existing project or create a new one.

```bash
# Create a new project
gcloud projects create PROJECT_ID --name="Mail Triage"

# Select an existing project
gcloud config set project PROJECT_ID
```

> **Note**: `PROJECT_ID` must be globally unique.

### 2. Enable Billing

Cloud Run, Vertex AI, and Cloud Storage all require billing.

```bash
# List billing accounts
gcloud billing accounts list

# Link a billing account to your project
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
```

Or configure via the [Cloud Console](https://console.cloud.google.com/billing).

### 3. Enable Required APIs

`deploy.sh` enables these automatically, but you can verify manually:

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

| API | Purpose |
|-----|---------|
| Cloud Run | Job execution |
| Artifact Registry | Container image storage |
| Eventarc | GCS event triggers |
| Cloud Scheduler | Periodic sweep |
| Cloud Storage | Email file storage |
| Vertex AI | Gemini LLM analysis |
| Secret Manager | Secure Slack token storage |

### 4. Verify Vertex AI Region

Use a region where the Gemini model is available.
`gemini-2.5-flash` is available in:

- `us-central1` (recommended)
- `europe-west1`
- `asia-northeast1` (Tokyo)

```bash
# Set the region
gcloud config set run/region us-central1
```

### 5. Local Development Authentication

Required for local test runs (not needed for deployment only).

```bash
# Set up Application Default Credentials
gcloud auth application-default login

# Configure Docker authentication (deploy.sh does this automatically)
gcloud auth configure-docker REGION-docker.pkg.dev
```

### 6. Verify gcloud Account Permissions

The account running `deploy.sh` must have the following permissions:

- **Project Owner** or **Editor** (recommended for initial setup)
- Minimum required individual roles:
  - `roles/iam.serviceAccountAdmin` — Create service accounts
  - `roles/resourcemanager.projectIamAdmin` — IAM bindings
  - `roles/storage.admin` — Create buckets
  - `roles/artifactregistry.admin` — Create repositories
  - `roles/run.admin` — Create Cloud Run Jobs
  - `roles/eventarc.admin` — Create triggers
  - `roles/cloudscheduler.admin` — Create schedulers
  - `roles/secretmanager.admin` — Create secrets

```bash
# Verify the authenticated account
gcloud auth list
```

---

## Slack Setup

### 1. Create a Slack App

1. Go to [Slack API: Your Apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. App Name: `mail-triage` (or any name you prefer)
4. Workspace: Select the workspace where notifications will be posted
5. Click **Create App**

### 2. Configure Bot Token Scopes

1. Open **OAuth & Permissions** from the left menu
2. Under **Scopes** → **Bot Token Scopes**, add:

| Scope | Purpose |
|-------|---------|
| `chat:write` | Post messages to channels |
| `files:write` | Attach files to threads (email body) |

> **Note**: `files:read` is not required. Only uploads are performed.

### 3. Install the App

1. Click **Install to Workspace** at the top of the **OAuth & Permissions** page
2. Review permissions and click **Allow**
3. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

> Store this token securely. You will register it in Secret Manager later.

### 4. Invite the Bot to a Channel

Add the bot to the target notification channel:

```
# Type in the Slack channel
/invite @mail-triage
```

Or:
1. Channel settings → **Integrations** → **Apps** → **Add apps**
2. Search for `mail-triage` and add it

> The bot cannot post to channels it has not been invited to (`not_in_channel` error).

### 5. Find Channel ID (Optional)

`SLACK_CHANNEL` accepts either a channel name (`#mail-digest`) or a channel ID (`C01XXXXXXXX`).
Using the channel ID is more reliable.

How to find the Channel ID:
1. Open the channel in Slack
2. Click the channel name → the **Channel ID** is shown at the bottom

---

## Create Deploy Configuration

```bash
cd mail-triage
cp deploy/deploy.env.template deploy/deploy.env
```

Edit `deploy/deploy.env`:

```bash
# ── Required ──
PROJECT_ID=your-gcp-project-id      # GCP project ID
REGION=us-central1                   # Cloud Run / Vertex AI region
BUCKET_NAME=your-mail-triage-bucket  # GCS bucket for email files
SLACK_CHANNEL=#mail-digest           # Slack notification channel

# ── Optional (defaults shown) ──
# SCHEDULER_CRON="*/30 * * * *"      # Sweep interval (default: every 30 min)
# SCHEDULER_TZ=Asia/Tokyo            # Timezone
# SUMMARY_LANG=ja                    # Force summary language
# GEMINI_MODEL=gemini-2.5-flash      # Gemini model name
# JOB_TIMEOUT=600                    # Job timeout (seconds)
# JOB_MEMORY=512Mi                   # Memory limit
```

> **Important**: `deploy/deploy.env` is in `.gitignore`. Never commit it.

---

## Run Deployment

```bash
# 1. Deploy all resources
./deploy/deploy.sh deploy/deploy.env

# 2. Register Slack bot token in Secret Manager
echo -n 'YOUR_SLACK_BOT_TOKEN' | \
  gcloud secrets versions add mail-triage-slack-bot-token \
    --data-file=- --project=PROJECT_ID
```

Resources created by `deploy.sh`:

| Resource | Name |
|----------|------|
| Service Account | `mail-triage-sa@PROJECT_ID.iam.gserviceaccount.com` |
| GCS Bucket | `gs://BUCKET_NAME` |
| Artifact Registry | `REGION-docker.pkg.dev/PROJECT_ID/mail-triage/` |
| Cloud Run Job | `mail-triage` |
| Eventarc Trigger | `mail-triage-gcs-trigger` |
| Cloud Scheduler | `mail-triage-sweep` |
| Secret | `mail-triage-slack-bot-token` |

---

## Verification

### Upload a Test Email

```bash
# Upload an .eml file to the inbox/ prefix
gcloud storage cp test.eml gs://BUCKET_NAME/inbox/

# The Eventarc trigger will automatically start the job
# A Slack message should arrive within seconds
```

### Check Job Execution Status

```bash
# List recent executions
gcloud run jobs executions list \
  --job=mail-triage \
  --region=REGION \
  --project=PROJECT_ID

# View logs for a specific execution
gcloud run jobs executions logs EXECUTION_NAME \
  --job=mail-triage \
  --region=REGION \
  --project=PROJECT_ID
```

### Manual Sweep Execution

```bash
gcloud run jobs execute mail-triage \
  --region=REGION \
  --project=PROJECT_ID
```

### Verify Processed Files

```bash
# Confirm files moved from inbox/ to processed/
gcloud storage ls gs://BUCKET_NAME/inbox/
gcloud storage ls gs://BUCKET_NAME/processed/
```

---

## Troubleshooting

### Slack

| Error | Cause | Fix |
|-------|-------|-----|
| `not_in_channel` | Bot not invited to the channel | Run `/invite @mail-triage` in the channel |
| `invalid_auth` | Token invalid or not set | Verify the token value in Secret Manager |
| `channel_not_found` | Incorrect channel name/ID | Use channel ID (`C01XXX`) instead of name |
| `missing_scope` | Required scope not granted | Add the scope in OAuth & Permissions, then reinstall the app |
| `ratelimited` | API rate limit | Automatic retry handles this; increase `SCHEDULER_CRON` interval for heavy loads |

### Gemini

| Error | Cause | Fix |
|-------|-------|-----|
| `PERMISSION_DENIED` | Vertex AI API not enabled or SA lacks permissions | `gcloud services enable aiplatform.googleapis.com` + verify IAM |
| `RESOURCE_EXHAUSTED` / 429 | Quota exceeded | Automatic retry (up to 6 attempts). Request a quota increase if frequent |
| `NOT_FOUND` | Invalid model name or region | Verify `GEMINI_MODEL` and `REGION` |

### GCS

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Forbidden` | SA lacks bucket access | Verify `roles/storage.objectAdmin` is granted |
| `404 Not Found` | Bucket or object does not exist | Check bucket name and prefix |

### Eventarc

| Error | Cause | Fix |
|-------|-------|-----|
| Trigger not firing | GCS service account lacks `pubsub.publisher` role | `deploy.sh` sets this up, but verify manually: `gcloud projects get-iam-policy PROJECT_ID` |
| Duplicate execution | Both Eventarc and Scheduler process the same file | Normal behavior (Eventarc processes first → Scheduler finds nothing new) |

### General

```bash
# View Cloud Run Job logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=mail-triage" \
  --project=PROJECT_ID \
  --limit=50 \
  --format="table(timestamp,textPayload)"
```

# mail-triage

GCS-based email analyzer that classifies emails using Gemini LLM and posts results to Slack.
Designed to run as a Google Cloud Run Job with Eventarc triggers and Cloud Scheduler.

## Features

- Parses `.eml` (RFC 2822) and `.msg` (OLE2/MAPI) email files from GCS
- Analyzes emails with Gemini LLM (category, priority, summary, tags, language)
- Posts formatted Block Kit notifications to Slack
- Supports two execution modes:
  - **Single file** (`--file`): Triggered by Eventarc on GCS object creation
  - **Sweep** (default): Processes all unprocessed files, triggered by Cloud Scheduler
- Defangs URLs/domains in summaries to prevent accidental clicks
- Prompt injection defense via nonce-tagged XML boundaries
- Exponential backoff retry for transient LLM errors

## Installation

```bash
# Clone
git clone https://github.com/nlink-jp/mail-triage.git
cd mail-triage

# Install dependencies
uv sync
```

## Configuration

All configuration is via environment variables with the `MAIL_TRIAGE_` prefix,
or via CLI flags.

| Variable | Flag | Default | Description |
|----------|------|---------|-------------|
| `MAIL_TRIAGE_BUCKET` | `--bucket` | (required) | GCS bucket name |
| `MAIL_TRIAGE_PREFIX` | `--prefix` | `inbox/` | Input prefix in bucket |
| `MAIL_TRIAGE_DONE_PREFIX` | `--done-prefix` | `processed/` | Processed prefix |
| `MAIL_TRIAGE_PROJECT` | `--project` | (required) | GCP project ID |
| `MAIL_TRIAGE_LOCATION` | `--location` | `us-central1` | Vertex AI location |
| `MAIL_TRIAGE_MODEL` | `--model` | `gemini-2.5-flash` | Gemini model name |
| `SUMMARY_LANG` | `--summary-lang` | (auto-detect) | Force summary language |
| `SLACK_BOT_TOKEN` | `--slack-token` | | Slack bot token |
| `SLACK_CHANNEL` | `--slack-channel` | | Target Slack channel |

## Usage

### Local execution

```bash
# Set up authentication
gcloud auth application-default login

# Sweep mode (process all unprocessed files)
uv run mail-triage --bucket my-bucket --project my-project --slack-channel '#mail-digest'

# Single file mode
uv run mail-triage --bucket my-bucket --project my-project --file inbox/alert.eml

# Dry run (parse and analyze without posting or moving)
uv run mail-triage --bucket my-bucket --project my-project --dry-run
```

### Cloud Run Job deployment

One-liner deployment using `deploy.sh`:

```bash
# 1. Copy and edit config
cp deploy/deploy.env.template deploy/deploy.env
# Edit deploy/deploy.env with your values

# 2. Deploy everything
./deploy/deploy.sh deploy/deploy.env

# 3. Add Slack bot token to Secret Manager
echo -n 'xoxb-...' | gcloud secrets versions add mail-triage-slack-bot-token \
  --data-file=- --project=PROJECT_ID
```

`deploy.sh` sets up:
- GCS bucket
- Artifact Registry repository
- Service account with required IAM roles
- Cloud Run Job with environment variables and secrets
- Eventarc trigger (GCS object finalize → job execution)
- Cloud Scheduler (periodic sweep fallback)

### Architecture

```
┌──────────────┐  object.finalize  ┌──────────────────┐
│ GCS          │──── Eventarc ────▶│ Cloud Run Job     │ ← single file mode
│ (inbox/)     │                   │ (mail-triage)   │
└──────────────┘                   └──────┬───────────┘
                                          │
┌──────────────┐  cron (fallback)         │
│ Cloud        │──── trigger ────▶ same job (sweep mode)
│ Scheduler    │                          │
└──────────────┘                   ┌──────┼──────┐
                                   ▼      ▼      ▼
                                  GCS  Gemini  Slack
```

## Email Analysis

Emails are classified into:

| Category | Emoji |
|----------|-------|
| security-alert | :rotating_light: |
| incident | :fire: |
| vulnerability | :warning: |
| compliance | :shield: |
| threat-intel | :mag: |
| newsletter | :newspaper: |
| announcement | :loudspeaker: |
| discussion | :speech_balloon: |
| other | :email: |

Priority levels: **high** (:red_circle:), **medium** (:large_orange_circle:), **low** (:white_circle:)

## Building

```bash
make test    # Run tests
make lint    # Lint check
make build   # Build wheel to dist/
```

## Required API Permissions

| Service | Permissions |
|---------|-------------|
| GCS | `storage.objects.list`, `get`, `create`, `delete` |
| Vertex AI | `aiplatform.endpoints.predict` |
| Slack | Bot scopes: `chat:write`, `files:write` |
| Secret Manager | `secretmanager.versions.access` |

## Documentation

- [README.md](README.md) (English)
- [README.ja.md](README.ja.md) (Japanese)
- [CHANGELOG.md](CHANGELOG.md)

# CLAUDE.md — mail-triage

## Project overview

GCS-based email analyzer for Cloud Run Jobs. Parses eml/msg files from GCS,
analyzes them with Gemini LLM, and posts results to Slack.

## Build & test

```bash
uv sync                  # Install dependencies
uv run pytest tests/ -v  # Run tests
make test                # Same via Makefile
make lint                # Ruff check + format
make build               # Build wheel to dist/
```

## Architecture

```
src/mail_triage/
├── cli.py          # Click CLI entry point (--file / --sweep modes)
├── config.py       # Pydantic BaseSettings configuration
├── models.py       # Pydantic data models (AnalysisResult, EmailData)
├── pipeline.py     # Orchestrates: GCS → parse → analyze → notify → move
├── parser/         # Email parsing (eml via stdlib, msg via python-oxmsg)
├── llm/            # Gemini LLM analysis (google-genai SDK)
├── gcs/            # GCS operations (list, download, move)
└── slack/          # Slack Block Kit notifications (slack_sdk)
```

## Key conventions

- **google-genai SDK** for Gemini (not vertexai SDK — deprecated)
- Config via environment variables with `MAIL_TRIAGE_` prefix
- GCS authentication via Application Default Credentials (ADC)
- Processed files moved from `inbox/` to `processed/` in same bucket
- All domain names in summaries must be defanged (`example[.]com`)

## Deployment

- `deploy/Dockerfile` — Cloud Run Job container
- `deploy/deploy.sh` — One-liner GCP setup (bucket, Cloud Run, Eventarc, Scheduler, IAM)
- `deploy/cloudrunjob.yaml` — Template with placeholders (never commit real values)

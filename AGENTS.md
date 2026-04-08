# AGENTS.md — mail-triage

## Summary

mail-triage is a GCS-based email analysis tool designed to run as a Google Cloud Run Job.
It parses `.eml` and `.msg` email files stored in GCS, classifies them using Gemini LLM
(category, priority, summary, tags), and posts formatted results to Slack.

## Build & test commands

```bash
uv sync                  # Install dependencies
uv run pytest tests/ -v  # Run tests
make test                # Run tests via Makefile
make lint                # Lint check
make build               # Build to dist/
```

## Key directory structure

```
mail-triage/
├── src/mail_triage/    # Main package (src-layout)
│   ├── cli.py            # Click CLI (--file / --sweep)
│   ├── config.py         # Pydantic BaseSettings
│   ├── models.py         # Data models
│   ├── pipeline.py       # Processing orchestrator
│   ├── parser/           # eml/msg parsing
│   ├── llm/              # Gemini analysis
│   ├── gcs/              # GCS operations
│   └── slack/            # Slack notifications
├── tests/                # pytest tests
├── deploy/               # Dockerfile, deploy.sh, cloudrunjob.yaml
├── pyproject.toml        # Project metadata (hatchling)
└── Makefile              # test, lint, build, clean
```

## Module path

Package: `mail_triage` (installed via `uv tool install .` or `pip install .`)
Entry point: `mail-triage` CLI command

## Environment variables

| Variable | Description |
|----------|-------------|
| `MAIL_TRIAGE_BUCKET` | GCS bucket name |
| `MAIL_TRIAGE_PREFIX` | Input prefix (default: `inbox/`) |
| `MAIL_TRIAGE_DONE_PREFIX` | Processed prefix (default: `processed/`) |
| `MAIL_TRIAGE_MODEL` | Gemini model (default: `gemini-2.5-flash`) |
| `MAIL_TRIAGE_PROJECT` | GCP project ID |
| `MAIL_TRIAGE_LOCATION` | Vertex AI location (default: `us-central1`) |
| `SLACK_BOT_TOKEN` | Slack bot token |
| `SLACK_CHANNEL` | Target Slack channel |
| `SUMMARY_LANG` | Force summary language (optional) |

## Gotchas

- Uses `google-genai` SDK, NOT the deprecated `vertexai` SDK
- GCS auth uses ADC — run `gcloud auth application-default login` locally
- Deploy script uses placeholder values; real values go in `.local.*` files
- `.msg` parsing requires `python-oxmsg` package

"""Configuration via environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """mail-triage configuration loaded from environment variables."""

    # GCS
    bucket: str = Field(default="", description="GCS bucket name")
    prefix: str = Field(default="inbox/", description="Input prefix in bucket")
    done_prefix: str = Field(default="processed/", description="Processed prefix in bucket")

    # Gemini
    project: str = Field(default="", description="GCP project ID")
    location: str = Field(default="us-central1", description="Vertex AI location")
    model: str = Field(default="gemini-2.5-flash", description="Gemini model name")
    summary_lang: str = Field(default="", description="Force summary language (e.g. ja, en)")

    # Slack
    slack_bot_token: str = Field(default="", description="Slack bot token")
    slack_channel: str = Field(default="", description="Slack channel to post to")

    # Runtime
    dry_run: bool = Field(default=False, description="Parse and analyze without posting or moving")

    model_config = {
        "env_prefix": "MAIL_TRIAGE_",
        "env_file": ".env",
        "extra": "ignore",
    }

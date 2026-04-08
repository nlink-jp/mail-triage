"""Slack Block Kit notification for email analysis results.

Rate limit handling:
- slack_sdk's built-in RateLimitErrorRetryHandler automatically retries
  on 429 responses, respecting the Retry-After header from Slack.
- A per-call throttle (_throttle) adds a minimum interval between API calls
  to stay well within Slack's Tier 3 limit (~50 req/min for chat.postMessage).
"""

from __future__ import annotations

import logging
import re
import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from mail_triage.config import Config
from mail_triage.models import AnalysisResult, Category, EmailData, Priority

logger = logging.getLogger(__name__)

# Minimum seconds between Slack API calls to avoid hitting rate limits
# during batch processing. Slack Tier 3 allows ~50 req/min ≈ 1.2s/req.
# We use 1.5s for safety margin.
_MIN_INTERVAL = 1.5
_last_call_time: float = 0.0

# Slack mrkdwn special characters that could break formatting
_MRKDWN_SPECIAL = re.compile(r"([*_~`\[\]|])")


def _throttle() -> None:
    """Ensure minimum interval between Slack API calls."""
    global _last_call_time
    now = time.monotonic()
    elapsed = now - _last_call_time
    if _last_call_time > 0 and elapsed < _MIN_INTERVAL:
        wait = _MIN_INTERVAL - elapsed
        logger.debug("Throttling Slack API call for %.1fs", wait)
        time.sleep(wait)
    _last_call_time = time.monotonic()


def _escape_mrkdwn(text: str) -> str:
    """Escape Slack mrkdwn special characters in untrusted text."""
    return _MRKDWN_SPECIAL.sub(r"\\\1", text)


def _slack_error_message(e: SlackApiError) -> str:
    """Safely extract error message from SlackApiError."""
    try:
        return e.response.get("error", str(e))
    except Exception:
        return str(e)


CATEGORY_EMOJI: dict[Category, str] = {
    Category.SECURITY_ALERT: ":rotating_light:",
    Category.INCIDENT: ":fire:",
    Category.VULNERABILITY: ":warning:",
    Category.COMPLIANCE: ":shield:",
    Category.THREAT_INTEL: ":mag:",
    Category.NEWSLETTER: ":newspaper:",
    Category.ANNOUNCEMENT: ":loudspeaker:",
    Category.DISCUSSION: ":speech_balloon:",
    Category.OTHER: ":email:",
}

PRIORITY_EMOJI: dict[Priority, str] = {
    Priority.HIGH: ":red_circle:",
    Priority.MEDIUM: ":large_orange_circle:",
    Priority.LOW: ":white_circle:",
}


def _build_success_blocks(email_data: EmailData, analysis: AnalysisResult) -> list[dict]:
    """Build Slack Block Kit blocks for a successful analysis."""
    cat_emoji = CATEGORY_EMOJI.get(analysis.category, ":email:")
    pri_emoji = PRIORITY_EMOJI.get(analysis.priority, ":white_circle:")
    tags_text = ", ".join(f"`{tag}`" for tag in analysis.tags) if analysis.tags else "_none_"

    safe_sender = _escape_mrkdwn(email_data.sender)
    safe_date = _escape_mrkdwn(email_data.date)

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{cat_emoji} {email_data.subject[:140]}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Category:*\n{cat_emoji} {analysis.category.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Priority:*\n{pri_emoji} {analysis.priority.value.upper()}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*From:*\n{safe_sender}"},
                {"type": "mrkdwn", "text": f"*Date:*\n{safe_date}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:*\n{analysis.summary[:2900]}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f":label: {tags_text}"},
            ],
        },
    ]


def _build_failure_blocks(email_data: EmailData, error: str) -> list[dict]:
    """Build Slack Block Kit blocks for a failed analysis."""
    safe_subject = _escape_mrkdwn(email_data.subject[:140])
    safe_sender = _escape_mrkdwn(email_data.sender)
    safe_date = _escape_mrkdwn(email_data.date)
    safe_error = _escape_mrkdwn(error[:500])

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":x: Mail Analysis Failed", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Subject:*\n{safe_subject}"},
                {"type": "mrkdwn", "text": f"*From:*\n{safe_sender}"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Date:*\n{safe_date}"},
                {"type": "mrkdwn", "text": f"*File:*\n`{email_data.source_file}`"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f":warning: {safe_error}"},
            ],
        },
    ]


def _get_client(config: Config) -> WebClient:
    client = WebClient(token=config.slack_bot_token)
    # Automatically retry on 429 (rate limited) using Retry-After header
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    return client


def post_analysis(email_data: EmailData, analysis: AnalysisResult, config: Config) -> None:
    """Post successful analysis result to Slack."""
    client = _get_client(config)
    blocks = _build_success_blocks(email_data, analysis)

    try:
        _throttle()
        result = client.chat_postMessage(
            channel=config.slack_channel,
            blocks=blocks,
            text=f"{CATEGORY_EMOJI.get(analysis.category, '')} {email_data.subject}",
        )
    except SlackApiError as e:
        logger.error("Slack post failed: %s", _slack_error_message(e))
        raise

    # Post email body as thread reply (file upload).
    # This is best-effort — if it fails, the main notification already succeeded.
    if email_data.body and result.get("ts"):
        try:
            _throttle()
            client.files_upload_v2(
                channel=config.slack_channel,
                thread_ts=result["ts"],
                content=email_data.body,
                filename=f"{email_data.source_file}.body.txt",
                title="Email Body",
            )
        except SlackApiError as e:
            logger.warning(
                "Thread file upload failed (main message posted successfully): %s",
                _slack_error_message(e),
            )


def post_failure(email_data: EmailData, error: str, config: Config) -> None:
    """Post failure notification to Slack."""
    client = _get_client(config)
    blocks = _build_failure_blocks(email_data, error)

    try:
        _throttle()
        client.chat_postMessage(
            channel=config.slack_channel,
            blocks=blocks,
            text=f":x: Mail Analysis Failed: {email_data.subject}",
        )
    except SlackApiError as e:
        logger.error("Slack failure notification failed: %s", _slack_error_message(e))

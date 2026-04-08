"""Tests for Slack Block Kit payload construction."""

from unittest.mock import MagicMock, patch

from mail_triage.config import Config
from mail_triage.models import AnalysisResult, Category, EmailData, Priority
from mail_triage.slack.notifier import (
    CATEGORY_EMOJI,
    PRIORITY_EMOJI,
    _build_failure_blocks,
    _build_success_blocks,
    post_analysis,
)


def _sample_email() -> EmailData:
    return EmailData(
        subject="Security Alert: Unusual Login",
        sender="security@example.com",
        date="Mon, 31 Mar 2026 10:00:00 +0900",
        body="Unusual login detected from IP 192.168.1.1",
        source_file="inbox/alert.eml",
    )


def _sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        category=Category.SECURITY_ALERT,
        priority=Priority.HIGH,
        summary="Unusual login activity detected from suspicious IP 192[.]168[.]1[.]1.",
        tags=["login", "alert", "authentication"],
        language="en",
    )


class TestBuildSuccessBlocks:
    def test_has_header(self):
        blocks = _build_success_blocks(_sample_email(), _sample_analysis())
        header = blocks[0]
        assert header["type"] == "header"
        assert "Security Alert" in header["text"]["text"]

    def test_has_category_and_priority(self):
        blocks = _build_success_blocks(_sample_email(), _sample_analysis())
        section = blocks[1]
        assert "SECURITY-ALERT" in section["fields"][0]["text"]
        assert "HIGH" in section["fields"][1]["text"]

    def test_has_from_and_date(self):
        blocks = _build_success_blocks(_sample_email(), _sample_analysis())
        section = blocks[2]
        assert "security@example.com" in section["fields"][0]["text"]
        assert "2026" in section["fields"][1]["text"]

    def test_has_summary(self):
        blocks = _build_success_blocks(_sample_email(), _sample_analysis())
        section = blocks[3]
        assert "Unusual login" in section["text"]["text"]

    def test_has_tags(self):
        blocks = _build_success_blocks(_sample_email(), _sample_analysis())
        context = blocks[4]
        assert "`login`" in context["elements"][0]["text"]

    def test_category_emoji_mapping(self):
        assert CATEGORY_EMOJI[Category.SECURITY_ALERT] == ":rotating_light:"
        assert CATEGORY_EMOJI[Category.INCIDENT] == ":fire:"
        assert CATEGORY_EMOJI[Category.OTHER] == ":email:"

    def test_priority_emoji_mapping(self):
        assert PRIORITY_EMOJI[Priority.HIGH] == ":red_circle:"
        assert PRIORITY_EMOJI[Priority.MEDIUM] == ":large_orange_circle:"
        assert PRIORITY_EMOJI[Priority.LOW] == ":white_circle:"

    def test_long_subject_truncated(self):
        email_data = _sample_email()
        email_data.subject = "A" * 200
        blocks = _build_success_blocks(email_data, _sample_analysis())
        header_text = blocks[0]["text"]["text"]
        assert len(header_text) < 200


class TestBuildFailureBlocks:
    def test_has_failure_header(self):
        blocks = _build_failure_blocks(_sample_email(), "LLM timeout")
        assert "Failed" in blocks[0]["text"]["text"]

    def test_has_error_context(self):
        blocks = _build_failure_blocks(_sample_email(), "LLM timeout")
        context = blocks[3]
        assert "LLM timeout" in context["elements"][0]["text"]

    def test_has_file_info(self):
        blocks = _build_failure_blocks(_sample_email(), "error")
        section = blocks[2]
        assert "alert.eml" in section["fields"][1]["text"]


class TestPostAnalysisFileUploadRecovery:
    """Thread file upload failure must not break the main notification."""

    @patch("mail_triage.slack.notifier._get_client")
    def test_file_upload_failure_does_not_raise(self, mock_get_client):
        from slack_sdk.errors import SlackApiError

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat_postMessage.return_value = {"ts": "1234567890.123456"}
        mock_client.files_upload_v2.side_effect = SlackApiError(
            message="upload_error", response=MagicMock(data={"error": "file_upload_failed"})
        )

        config = Config(bucket="b", project="p", slack_bot_token="xoxb-test", slack_channel="#test")
        # Should NOT raise even though files_upload_v2 fails
        post_analysis(_sample_email(), _sample_analysis(), config)

        mock_client.chat_postMessage.assert_called_once()
        mock_client.files_upload_v2.assert_called_once()

    @patch("mail_triage.slack.notifier._get_client")
    def test_file_upload_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat_postMessage.return_value = {"ts": "1234567890.123456"}

        config = Config(bucket="b", project="p", slack_bot_token="xoxb-test", slack_channel="#test")
        post_analysis(_sample_email(), _sample_analysis(), config)

        mock_client.files_upload_v2.assert_called_once()
        call_kwargs = mock_client.files_upload_v2.call_args[1]
        assert call_kwargs["thread_ts"] == "1234567890.123456"
        assert call_kwargs["filename"].endswith(".body.txt")

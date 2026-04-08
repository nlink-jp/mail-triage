"""Tests for processing pipeline."""

from unittest.mock import MagicMock, patch

from mail_triage.config import Config
from mail_triage.models import AnalysisResult, Category, EmailData, Priority
from mail_triage.pipeline import process_single_file, sweep


def _config(**overrides) -> Config:
    defaults = {
        "bucket": "test-bucket",
        "prefix": "inbox/",
        "done_prefix": "processed/",
        "project": "test-project",
        "dry_run": True,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _sample_eml_bytes() -> bytes:
    return (
        "From: sender@example.com\r\n"
        "Subject: Test Alert\r\n"
        "Date: Mon, 31 Mar 2026 10:00:00 +0900\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Suspicious activity detected.\r\n"
    ).encode("utf-8")


class TestProcessSingleFile:
    @patch("mail_triage.pipeline.analyze_email")
    def test_successful_processing(self, mock_analyze):
        mock_analyze.return_value = AnalysisResult(
            category=Category.SECURITY_ALERT,
            priority=Priority.HIGH,
            summary="Alert summary",
            tags=["alert"],
            language="en",
        )

        gcs = MagicMock()
        gcs.download.return_value = _sample_eml_bytes()

        config = _config()
        result = process_single_file("inbox/test.eml", config, gcs)

        assert result.success
        assert result.email.subject == "Test Alert"
        assert result.analysis is not None
        assert result.analysis.category == Category.SECURITY_ALERT

    def test_download_failure(self):
        gcs = MagicMock()
        gcs.download.side_effect = Exception("Network error")

        result = process_single_file("inbox/test.eml", _config(), gcs)

        assert not result.success
        assert "Download failed" in result.error

    def test_parse_failure(self):
        gcs = MagicMock()
        gcs.download.return_value = b"not a valid email"

        result = process_single_file("inbox/test.xyz", _config(), gcs)

        assert not result.success
        assert "Parse failed" in result.error

    @patch("mail_triage.pipeline.analyze_email")
    def test_llm_failure_still_returns_email(self, mock_analyze):
        mock_analyze.side_effect = Exception("LLM timeout")

        gcs = MagicMock()
        gcs.download.return_value = _sample_eml_bytes()

        result = process_single_file("inbox/test.eml", _config(), gcs)

        assert result.email.subject == "Test Alert"
        assert result.analysis is None
        assert "LLM analysis failed" in result.error


class TestSweep:
    @patch("mail_triage.pipeline.GCSClient")
    @patch("mail_triage.pipeline.analyze_email")
    def test_sweep_processes_all_files(self, mock_analyze, mock_gcs_cls):
        mock_gcs = MagicMock()
        mock_gcs_cls.return_value = mock_gcs
        mock_gcs.list_unprocessed.return_value = ["inbox/a.eml", "inbox/b.eml"]
        mock_gcs.download.return_value = _sample_eml_bytes()
        mock_analyze.return_value = AnalysisResult(
            category=Category.OTHER,
            priority=Priority.LOW,
            summary="test",
            tags=[],
            language="en",
        )

        results = sweep(_config())
        assert len(results) == 2
        assert all(r.success for r in results)

    @patch("mail_triage.pipeline.GCSClient")
    def test_sweep_empty_bucket(self, mock_gcs_cls):
        mock_gcs = MagicMock()
        mock_gcs_cls.return_value = mock_gcs
        mock_gcs.list_unprocessed.return_value = []

        results = sweep(_config())
        assert results == []

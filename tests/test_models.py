"""Tests for data models."""

from mail_triage.models import (
    AnalysisResult,
    Category,
    EmailData,
    Priority,
    ProcessResult,
)


class TestCategory:
    def test_values(self):
        assert Category.SECURITY_ALERT.value == "security-alert"
        assert Category.INCIDENT.value == "incident"
        assert Category.OTHER.value == "other"

    def test_from_string(self):
        assert Category("security-alert") == Category.SECURITY_ALERT
        assert Category("other") == Category.OTHER


class TestPriority:
    def test_values(self):
        assert Priority.HIGH.value == "high"
        assert Priority.MEDIUM.value == "medium"
        assert Priority.LOW.value == "low"


class TestEmailData:
    def test_defaults(self):
        email = EmailData()
        assert email.subject == ""
        assert email.sender == ""
        assert email.date == ""
        assert email.body == ""
        assert email.source_file == ""


class TestAnalysisResult:
    def test_defaults(self):
        result = AnalysisResult()
        assert result.category == Category.OTHER
        assert result.priority == Priority.LOW
        assert result.summary == ""
        assert result.tags == []
        assert result.language == "en"


class TestProcessResult:
    def test_success_result(self):
        result = ProcessResult(
            source_path="inbox/test.eml",
            email=EmailData(subject="Test"),
            analysis=AnalysisResult(category=Category.SECURITY_ALERT),
            success=True,
        )
        assert result.success
        assert result.error is None

    def test_failure_result(self):
        result = ProcessResult(
            source_path="inbox/test.eml",
            email=EmailData(),
            error="Parse failed",
            success=False,
        )
        assert not result.success
        assert result.error == "Parse failed"

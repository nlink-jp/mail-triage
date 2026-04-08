"""Tests for the unified email parser dispatch."""

import pytest

from mail_triage.parser.parse import parse_email_bytes


def _make_simple_eml() -> bytes:
    return (
        "From: sender@example.com\r\n"
        "Subject: Test\r\n"
        "Date: Mon, 31 Mar 2026 10:00:00 +0900\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Hello\r\n"
    ).encode("utf-8")


class TestParseEmailBytes:
    def test_eml_dispatch(self):
        result = parse_email_bytes(_make_simple_eml(), "test.eml")
        assert result.subject == "Test"

    def test_eml_case_insensitive(self):
        result = parse_email_bytes(_make_simple_eml(), "test.EML")
        assert result.subject == "Test"

    def test_unsupported_extension(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            parse_email_bytes(b"", "test.txt")

    def test_msg_dispatch_import_error(self):
        """MSG dispatch works but may fail if extract-msg can't parse garbage bytes."""
        with pytest.raises(Exception):
            parse_email_bytes(b"not a real msg file", "test.msg")

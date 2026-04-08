"""Tests for EML parser."""

from mail_triage.parser.eml import parse_eml


def _make_eml(
    subject: str = "Test Subject",
    sender: str = "sender@example.com",
    date: str = "Mon, 31 Mar 2026 10:00:00 +0900",
    body: str = "Hello, this is a test email.",
    content_type: str = "text/plain",
    charset: str = "utf-8",
) -> bytes:
    """Build a minimal EML file as bytes."""
    return (
        f"From: {sender}\r\n"
        f"To: recipient@example.com\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date}\r\n"
        f"Content-Type: {content_type}; charset={charset}\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


class TestParseEml:
    def test_basic_text_email(self):
        data = _make_eml()
        result = parse_eml(data, source_file="test.eml")

        assert result.subject == "Test Subject"
        assert result.sender == "sender@example.com"
        assert "2026" in result.date
        assert "Hello, this is a test email." in result.body
        assert result.source_file == "test.eml"

    def test_html_email(self):
        html_body = "<html><body><p>Hello <b>world</b></p></body></html>"
        data = _make_eml(body=html_body, content_type="text/html")
        result = parse_eml(data)

        assert "Hello" in result.body
        assert "world" in result.body
        assert "<html>" not in result.body

    def test_multipart_email(self):
        raw = (
            "From: sender@example.com\r\n"
            "Subject: Multipart Test\r\n"
            "Date: Mon, 31 Mar 2026 10:00:00 +0900\r\n"
            "Content-Type: multipart/alternative; boundary=boundary123\r\n"
            "\r\n"
            "--boundary123\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Plain text version\r\n"
            "--boundary123\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "\r\n"
            "<html><body>HTML version</body></html>\r\n"
            "--boundary123--\r\n"
        ).encode("utf-8")

        result = parse_eml(raw)
        assert result.subject == "Multipart Test"
        # Should prefer plain text
        assert "Plain text version" in result.body

    def test_empty_body(self):
        data = (
            "From: sender@example.com\r\n"
            "Subject: Empty\r\n"
            "Date: Mon, 31 Mar 2026 10:00:00 +0900\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
        ).encode("utf-8")

        result = parse_eml(data)
        assert result.subject == "Empty"
        assert result.body == ""

    def test_encoded_subject(self):
        """Test RFC 2047 encoded subject (Japanese)."""
        data = (
            "From: sender@example.com\r\n"
            "Subject: =?UTF-8?B?44OG44K544OI5Lu2?=\r\n"
            "Date: Mon, 31 Mar 2026 10:00:00 +0900\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Body\r\n"
        ).encode("utf-8")

        result = parse_eml(data)
        assert result.subject == "テスト件"

    def test_source_file_preserved(self):
        data = _make_eml()
        result = parse_eml(data, source_file="inbox/2026-03-31_test.eml")
        assert result.source_file == "inbox/2026-03-31_test.eml"

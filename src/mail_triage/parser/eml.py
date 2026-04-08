"""Parse .eml files using Python stdlib email module."""

from __future__ import annotations

import email
import email.header
import email.policy
import email.utils
from html.parser import HTMLParser
from io import StringIO

from mail_triage.models import EmailData

# Maximum body size to prevent OOM on huge emails.
# LLM prompt truncates further, but this prevents holding gigabytes in memory.
_MAX_BODY_BYTES = 1_000_000  # 1 MB


class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and extract plain text."""

    def __init__(self) -> None:
        super().__init__()
        self._result = StringIO()

    def handle_data(self, data: str) -> None:
        self._result.write(data)

    def get_text(self) -> str:
        return self._result.getvalue().strip()


def _strip_html(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    decoded_parts: list[str] = []
    for part, charset in email.header.decode_header(value):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return " ".join(decoded_parts)


def _extract_body(msg: email.message.EmailMessage) -> str:
    """Extract plain text body from email message."""
    # Try plain text first
    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        content = body.get_content()
        if isinstance(content, str):
            return content.strip()

    # Fall back to HTML
    body = msg.get_body(preferencelist=("html",))
    if body is not None:
        content = body.get_content()
        if isinstance(content, str):
            return _strip_html(content)

    # Walk all parts as last resort
    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "text/plain":
            payload = part.get_content()
            if isinstance(payload, str):
                return payload.strip()
        elif content_type == "text/html":
            payload = part.get_content()
            if isinstance(payload, str):
                return _strip_html(payload)

    return ""


def parse_eml(data: bytes, source_file: str = "") -> EmailData:
    """Parse .eml file bytes into EmailData."""
    msg = email.message_from_bytes(data, policy=email.policy.default)

    subject = _decode_header(msg.get("Subject"))
    sender = _decode_header(msg.get("From"))
    date = msg.get("Date", "")
    body = _extract_body(msg)[:_MAX_BODY_BYTES]

    return EmailData(
        subject=subject,
        sender=sender,
        date=date,
        body=body,
        source_file=source_file,
    )

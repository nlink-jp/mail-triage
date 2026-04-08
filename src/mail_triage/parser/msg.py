"""Parse .msg files using extract-msg."""

from __future__ import annotations

import logging
from html.parser import HTMLParser
from io import StringIO

from mail_triage.models import EmailData

logger = logging.getLogger(__name__)

# Maximum body size to prevent OOM on huge emails.
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


def parse_msg(data: bytes, source_file: str = "") -> EmailData:
    """Parse .msg file bytes into EmailData.

    Uses extract-msg which handles OLE2/CFBF format, MAPI properties,
    and charset conversion (Shift_JIS, ISO-2022-JP, etc.) internally.
    """
    try:
        import extract_msg
    except ImportError:
        raise ImportError("extract-msg is required to parse .msg files: pip install extract-msg")

    msg = extract_msg.Message(data)
    try:
        subject = msg.subject or ""
        sender = msg.sender or ""
        date = msg.date or ""
        if hasattr(date, "isoformat"):
            date = date.isoformat()

        # Prefer plain text body, fall back to HTML
        body = msg.body or ""
        if not body and msg.htmlBody:
            html = msg.htmlBody
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")
            body = _strip_html(html)

        return EmailData(
            subject=subject,
            sender=sender,
            date=str(date),
            body=body[:_MAX_BODY_BYTES],
            source_file=source_file,
        )
    finally:
        msg.close()

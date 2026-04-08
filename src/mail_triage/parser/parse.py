"""Unified email parser dispatching by file extension."""

from __future__ import annotations

from mail_triage.models import EmailData
from mail_triage.parser.eml import parse_eml
from mail_triage.parser.msg import parse_msg


def parse_email_bytes(data: bytes, filename: str) -> EmailData:
    """Parse email bytes, dispatching to the correct parser based on file extension."""
    lower = filename.lower()
    if lower.endswith(".msg"):
        return parse_msg(data, source_file=filename)
    elif lower.endswith(".eml"):
        return parse_eml(data, source_file=filename)
    else:
        raise ValueError(f"Unsupported file extension: {filename} (expected .eml or .msg)")

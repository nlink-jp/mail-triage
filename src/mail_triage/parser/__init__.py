"""Email parser package."""

from mail_triage.parser.eml import parse_eml
from mail_triage.parser.msg import parse_msg
from mail_triage.parser.parse import parse_email_bytes

__all__ = ["parse_eml", "parse_msg", "parse_email_bytes"]

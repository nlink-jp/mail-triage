"""Slack notification package."""

from mail_triage.slack.notifier import post_analysis, post_failure

__all__ = ["post_analysis", "post_failure"]

"""CLI entry point for mail-triage."""

from __future__ import annotations

import logging
import sys

import click

from mail_triage.config import Config


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


@click.command()
@click.option("--file", "file_path", default=None, help="GCS blob path to process (single file mode)")
@click.option("--bucket", envvar="MAIL_TRIAGE_BUCKET", default=None, help="GCS bucket name")
@click.option("--prefix", envvar="MAIL_TRIAGE_PREFIX", default="inbox/", help="Input prefix in bucket")
@click.option("--done-prefix", envvar="MAIL_TRIAGE_DONE_PREFIX", default="processed/", help="Processed prefix")
@click.option("--project", envvar="MAIL_TRIAGE_PROJECT", default=None, help="GCP project ID")
@click.option("--location", envvar="MAIL_TRIAGE_LOCATION", default="us-central1", help="Vertex AI location")
@click.option("--model", envvar="MAIL_TRIAGE_MODEL", default="gemini-2.5-flash", help="Gemini model name")
@click.option("--summary-lang", envvar="SUMMARY_LANG", default="", help="Force summary language")
@click.option("--slack-channel", envvar="SLACK_CHANNEL", default=None, help="Slack channel")
@click.option("--slack-token", envvar="SLACK_BOT_TOKEN", default=None, help="Slack bot token")
@click.option("--dry-run", is_flag=True, help="Parse and analyze without posting or moving")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(
    file_path: str | None,
    bucket: str | None,
    prefix: str,
    done_prefix: str,
    project: str | None,
    location: str,
    model: str,
    summary_lang: str,
    slack_channel: str | None,
    slack_token: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Analyze email files from GCS with LLM and post results to Slack.

    In single-file mode (--file), processes one specific GCS object.
    In sweep mode (default), processes all unprocessed files in the bucket prefix.
    """
    _setup_logging(verbose)

    if not bucket:
        click.echo("Error: --bucket or MAIL_TRIAGE_BUCKET is required", err=True)
        sys.exit(1)

    if not project:
        click.echo("Error: --project or MAIL_TRIAGE_PROJECT is required", err=True)
        sys.exit(1)

    config = Config(
        bucket=bucket,
        prefix=prefix,
        done_prefix=done_prefix,
        project=project,
        location=location,
        model=model,
        summary_lang=summary_lang,
        slack_bot_token=slack_token or "",
        slack_channel=slack_channel or "",
        dry_run=dry_run,
    )

    from mail_triage.pipeline import process_file, sweep

    if file_path:
        result = process_file(file_path, config)
        if not result.success:
            click.echo(f"Failed: {result.error}", err=True)
            sys.exit(1)
        click.echo(f"Processed: {result.source_path}")
    else:
        results = sweep(config)
        failed = [r for r in results if not r.success]
        if failed:
            for r in failed:
                click.echo(f"Failed: {r.source_path}: {r.error}", err=True)
            sys.exit(1)
        click.echo(f"Processed {len(results)} file(s)")

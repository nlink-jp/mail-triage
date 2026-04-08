"""Processing pipeline: GCS → parse → analyze → notify → move."""

from __future__ import annotations

import logging
import os

from mail_triage.config import Config
from mail_triage.gcs.client import GCSClient
from mail_triage.llm.analyzer import analyze_email
from mail_triage.models import EmailData, ProcessResult
from mail_triage.parser import parse_email_bytes
from mail_triage.slack.notifier import post_analysis, post_failure

logger = logging.getLogger(__name__)


def process_single_file(blob_name: str, config: Config, gcs_client: GCSClient) -> ProcessResult:
    """Process a single email file from GCS.

    Steps:
    1. Download from GCS
    2. Parse email (eml/msg)
    3. Analyze with LLM
    4. Post result to Slack
    5. Move to processed prefix
    """
    filename = os.path.basename(blob_name)
    logger.info("Processing: %s", blob_name)

    # 1. Download
    try:
        data = gcs_client.download(blob_name)
    except Exception as e:
        logger.error("Failed to download %s: %s", blob_name, e)
        return ProcessResult(
            source_path=blob_name,
            email=EmailData(source_file=filename),
            error=f"Download failed: {e}",
            success=False,
        )

    # 2. Parse
    try:
        email_data = parse_email_bytes(data, filename)
    except Exception as e:
        logger.error("Failed to parse %s: %s", blob_name, e)
        return ProcessResult(
            source_path=blob_name,
            email=EmailData(source_file=filename),
            error=f"Parse failed: {e}",
            success=False,
        )

    # 3. Analyze with LLM
    analysis = None
    analysis_error = None
    try:
        analysis = analyze_email(email_data, config)
        logger.info(
            "Analyzed %s: category=%s priority=%s",
            filename,
            analysis.category.value,
            analysis.priority.value,
        )
    except Exception as e:
        analysis_error = f"LLM analysis failed: {e}"
        logger.error("LLM analysis failed for %s: %s", blob_name, e)

    # 4. Post to Slack
    if not config.dry_run and config.slack_bot_token and config.slack_channel:
        try:
            if analysis:
                post_analysis(email_data, analysis, config)
            else:
                post_failure(email_data, analysis_error or "Unknown error", config)
        except Exception as e:
            logger.error("Slack post failed for %s: %s", blob_name, e)

    # 5. Move to processed (even if analysis failed — parsing succeeded)
    if not config.dry_run:
        try:
            gcs_client.move_to_processed(blob_name)
        except Exception as e:
            logger.error("Failed to move %s to processed: %s", blob_name, e)
            return ProcessResult(
                source_path=blob_name,
                email=email_data,
                analysis=analysis,
                error=f"Move failed: {e}",
                success=False,
            )

    return ProcessResult(
        source_path=blob_name,
        email=email_data,
        analysis=analysis,
        error=analysis_error,
        success=analysis_error is None,
    )


def sweep(config: Config) -> list[ProcessResult]:
    """Process all unprocessed email files in the GCS bucket."""
    gcs_client = GCSClient(config)
    blob_names = gcs_client.list_unprocessed()

    if not blob_names:
        logger.info("No unprocessed email files found in gs://%s/%s", config.bucket, config.prefix)
        return []

    logger.info("Found %d unprocessed email file(s)", len(blob_names))
    results = []
    for blob_name in blob_names:
        result = process_single_file(blob_name, config, gcs_client)
        results.append(result)

    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded
    logger.info("Processing complete: %d succeeded, %d failed", succeeded, failed)
    return results


def process_file(blob_name: str, config: Config) -> ProcessResult:
    """Process a specific file from GCS (Eventarc single-file mode)."""
    gcs_client = GCSClient(config)
    return process_single_file(blob_name, config, gcs_client)

"""GCS client for listing, downloading, and moving email files."""

from __future__ import annotations

import logging

from google.api_core.exceptions import NotFound
from google.cloud import storage

from mail_triage.config import Config

logger = logging.getLogger(__name__)

# Supported email file extensions
_EMAIL_EXTENSIONS = (".eml", ".msg")


class GCSClient:
    """Client for GCS operations on email files."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = storage.Client(project=config.project)
        self._bucket = self._client.bucket(config.bucket)

    def list_unprocessed(self) -> list[str]:
        """List email files in the input prefix that haven't been processed yet.

        Returns blob names (full paths including prefix) for .eml and .msg files.
        """
        blobs = self._client.list_blobs(
            self._bucket,
            prefix=self._config.prefix,
        )
        results = []
        for blob in blobs:
            lower_name = blob.name.lower()
            if any(lower_name.endswith(ext) for ext in _EMAIL_EXTENSIONS):
                results.append(blob.name)
        return sorted(results)

    def download(self, blob_name: str) -> bytes:
        """Download a blob's contents as bytes.

        Raises google.api_core.exceptions.NotFound if the blob does not exist
        (e.g. already processed by a concurrent run).
        """
        blob = self._bucket.blob(blob_name)
        data = blob.download_as_bytes()
        logger.info("Downloaded %s (%d bytes)", blob_name, len(data))
        return data

    def move_to_processed(self, blob_name: str) -> str:
        """Move a blob from input prefix to processed prefix.

        Copy-then-delete is not atomic. If the source blob was already deleted
        by a concurrent run, the NotFound on delete is logged and ignored.

        Returns the new blob name.
        """
        # Replace input prefix with done prefix
        prefix = self._config.prefix
        done_prefix = self._config.done_prefix
        if blob_name.startswith(prefix):
            new_name = done_prefix + blob_name[len(prefix):]
        else:
            new_name = done_prefix + blob_name

        source_blob = self._bucket.blob(blob_name)
        self._bucket.copy_blob(source_blob, self._bucket, new_name)

        try:
            source_blob.delete()
        except NotFound:
            logger.warning("Source blob %s already deleted (concurrent run), skipping delete", blob_name)

        logger.info("Moved %s → %s", blob_name, new_name)
        return new_name

"""Tests for GCS client using mocks."""

from unittest.mock import MagicMock, patch

from mail_triage.config import Config
from mail_triage.gcs.client import GCSClient


def _config(**overrides) -> Config:
    defaults = {
        "bucket": "test-bucket",
        "prefix": "inbox/",
        "done_prefix": "processed/",
        "project": "test-project",
    }
    defaults.update(overrides)
    return Config(**defaults)


class TestGCSClient:
    @patch("mail_triage.gcs.client.storage.Client")
    def test_list_unprocessed_filters_extensions(self, mock_storage_cls):
        mock_client = MagicMock()
        mock_storage_cls.return_value = mock_client

        mock_blobs = [
            MagicMock(name="inbox/alert.eml"),
            MagicMock(name="inbox/report.msg"),
            MagicMock(name="inbox/readme.txt"),
            MagicMock(name="inbox/data.csv"),
        ]
        # Set .name attribute explicitly (MagicMock uses name for repr)
        mock_blobs[0].name = "inbox/alert.eml"
        mock_blobs[1].name = "inbox/report.msg"
        mock_blobs[2].name = "inbox/readme.txt"
        mock_blobs[3].name = "inbox/data.csv"
        mock_client.list_blobs.return_value = mock_blobs

        client = GCSClient(_config())
        result = client.list_unprocessed()

        assert result == ["inbox/alert.eml", "inbox/report.msg"]

    @patch("mail_triage.gcs.client.storage.Client")
    def test_list_unprocessed_empty(self, mock_storage_cls):
        mock_client = MagicMock()
        mock_storage_cls.return_value = mock_client
        mock_client.list_blobs.return_value = []

        client = GCSClient(_config())
        result = client.list_unprocessed()
        assert result == []

    @patch("mail_triage.gcs.client.storage.Client")
    def test_download(self, mock_storage_cls):
        mock_client = MagicMock()
        mock_storage_cls.return_value = mock_client
        mock_bucket = mock_client.bucket.return_value
        mock_blob = mock_bucket.blob.return_value
        mock_blob.download_as_bytes.return_value = b"email content"

        client = GCSClient(_config())
        data = client.download("inbox/test.eml")

        assert data == b"email content"
        mock_bucket.blob.assert_called_with("inbox/test.eml")

    @patch("mail_triage.gcs.client.storage.Client")
    def test_move_to_processed(self, mock_storage_cls):
        mock_client = MagicMock()
        mock_storage_cls.return_value = mock_client
        mock_bucket = mock_client.bucket.return_value

        client = GCSClient(_config())
        new_name = client.move_to_processed("inbox/test.eml")

        assert new_name == "processed/test.eml"
        mock_bucket.copy_blob.assert_called_once()
        mock_bucket.blob.return_value.delete.assert_called_once()

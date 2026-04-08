"""Tests for configuration."""

from mail_triage.config import Config


class TestConfig:
    def test_defaults(self):
        config = Config(bucket="b", project="p")
        assert config.prefix == "inbox/"
        assert config.done_prefix == "processed/"
        assert config.location == "us-central1"
        assert config.model == "gemini-2.5-flash"
        assert config.dry_run is False

    def test_env_prefix(self):
        """Config model should use MAIL_TRIAGE_ prefix."""
        assert Config.model_config["env_prefix"] == "MAIL_TRIAGE_"

    def test_override(self):
        config = Config(
            bucket="my-bucket",
            prefix="input/",
            done_prefix="done/",
            project="my-project",
            model="gemini-2.0-flash",
            dry_run=True,
        )
        assert config.bucket == "my-bucket"
        assert config.prefix == "input/"
        assert config.done_prefix == "done/"
        assert config.model == "gemini-2.0-flash"
        assert config.dry_run is True

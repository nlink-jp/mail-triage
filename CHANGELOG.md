# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-04-08

### Added

- Email parser for `.eml` (Python stdlib) and `.msg` (extract-msg) formats
- Gemini LLM analysis with structured JSON output (category, priority, summary, tags, language)
- Prompt injection defense via nonce-tagged XML boundaries
- GCS client for listing, downloading, and moving email files
- Slack Block Kit notifications with category/priority emojis
- Two execution modes: single file (`--file`) and sweep (default)
- Cloud Run Job deployment with Eventarc trigger and Cloud Scheduler
- One-liner deployment script (`deploy/deploy.sh`)
- Exponential backoff retry for transient LLM errors
- URL/domain defanging in analysis summaries
- Comprehensive test suite (60 tests)

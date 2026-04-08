"""Tests for LLM response parsing and validation."""

import json

import pytest

from mail_triage.llm.analyzer import _parse_response
from mail_triage.models import Category, Priority


class TestParseResponse:
    def test_valid_response(self):
        data = {
            "category": "security-alert",
            "priority": "high",
            "summary": "A phishing email targeting credentials.",
            "tags": ["phishing", "credentials"],
            "language": "en",
        }
        result = _parse_response(json.dumps(data))

        assert result.category == Category.SECURITY_ALERT
        assert result.priority == Priority.HIGH
        assert "phishing" in result.summary
        assert result.tags == ["phishing", "credentials"]
        assert result.language == "en"

    def test_unknown_category_defaults_to_other(self):
        data = {
            "category": "unknown-category",
            "priority": "low",
            "summary": "Some summary",
            "tags": [],
            "language": "en",
        }
        result = _parse_response(json.dumps(data))
        assert result.category == Category.OTHER

    def test_unknown_priority_defaults_to_low(self):
        data = {
            "category": "other",
            "priority": "critical",
            "summary": "Some summary",
            "tags": [],
            "language": "en",
        }
        result = _parse_response(json.dumps(data))
        assert result.priority == Priority.LOW

    def test_tags_limited_to_five(self):
        data = {
            "category": "other",
            "priority": "low",
            "summary": "Summary",
            "tags": ["a", "b", "c", "d", "e", "f", "g"],
            "language": "en",
        }
        result = _parse_response(json.dumps(data))
        assert len(result.tags) == 5

    def test_markdown_code_fence_stripped(self):
        raw = '```json\n{"category":"other","priority":"low","summary":"test","tags":[],"language":"en"}\n```'
        result = _parse_response(raw)
        assert result.summary == "test"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json")

    def test_missing_fields_use_defaults(self):
        result = _parse_response("{}")
        assert result.category == Category.OTHER
        assert result.priority == Priority.LOW
        assert result.summary == ""
        assert result.tags == []
        assert result.language == "en"

    def test_non_list_tags_handled(self):
        data = {
            "category": "other",
            "priority": "low",
            "summary": "test",
            "tags": "not-a-list",
            "language": "en",
        }
        result = _parse_response(json.dumps(data))
        assert result.tags == []

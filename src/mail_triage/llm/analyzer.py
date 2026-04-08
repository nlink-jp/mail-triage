"""Gemini LLM email analyzer with retry logic.

Rate limit handling:
- Exponential backoff with ±1s jitter on 429/resource_exhausted/5xx errors.
- Delay sequence: 5s, 10s, 20s, 40s, 80s, 120s (capped).
- Max 6 attempts total (initial + 5 retries).
"""

from __future__ import annotations

import json
import logging
import random
import time

from google import genai
from google.genai import types

from mail_triage.config import Config
from mail_triage.llm.prompt import build_system_prompt, build_user_prompt
from mail_triage.models import AnalysisResult, EmailData

logger = logging.getLogger(__name__)

# Retry config: exponential backoff with jitter
_MAX_RETRIES = 5
_BASE_DELAY = 5.0
_MAX_DELAY = 120.0
_JITTER = 1.0


def _create_client(config: Config) -> genai.Client:
    """Create a Gemini client using Vertex AI."""
    return genai.Client(
        vertexai=True,
        project=config.project,
        location=config.location,
    )


def _parse_response(text: str) -> AnalysisResult:
    """Parse LLM response JSON into AnalysisResult.

    Validates that category and priority values are within expected enums.
    Also checks for semantic inconsistencies.
    """
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)

    # Validate and coerce fields
    from mail_triage.models import Category, Priority

    category = data.get("category", "other")
    try:
        category = Category(category)
    except ValueError:
        logger.warning("Unknown category '%s', defaulting to 'other'", category)
        category = Category.OTHER

    priority = data.get("priority", "low")
    try:
        priority = Priority(priority)
    except ValueError:
        logger.warning("Unknown priority '%s', defaulting to 'low'", priority)
        priority = Priority.LOW

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags[:5]]

    summary = str(data.get("summary", ""))
    language = str(data.get("language", "en"))

    # Semantic validation: security-alert/incident/vulnerability should not be low priority
    if category in (Category.SECURITY_ALERT, Category.INCIDENT, Category.VULNERABILITY) and priority == Priority.LOW:
        logger.warning(
            "Category '%s' with priority 'low' is unusual — keeping LLM judgment but logging for review",
            category.value,
        )

    return AnalysisResult(
        category=category,
        priority=priority,
        summary=summary,
        tags=tags,
        language=language,
    )


def analyze_email(email_data: EmailData, config: Config) -> AnalysisResult:
    """Analyze an email using Gemini LLM.

    Retries on transient errors with exponential backoff.
    """
    client = _create_client(config)

    system_prompt = build_system_prompt(config.summary_lang)
    user_prompt = build_user_prompt(
        subject=email_data.subject,
        sender=email_data.sender,
        date=email_data.date,
        body=email_data.body,
    )

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=config.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )

            if not response.text:
                raise ValueError("Empty response from LLM")

            return _parse_response(response.text)

        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = any(k in error_str for k in ["429", "resource_exhausted", "503", "500", "deadline"])

            if not is_retryable or attempt == _MAX_RETRIES:
                logger.error("LLM analysis failed (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES + 1, e)
                raise

            delay = min(_BASE_DELAY * (2**attempt), _MAX_DELAY)
            jitter = random.uniform(-_JITTER, _JITTER)
            delay = max(0, delay + jitter)
            logger.warning("LLM call failed (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, _MAX_RETRIES + 1, delay, e)
            time.sleep(delay)

    # Should not reach here, but satisfy type checker
    raise last_error  # type: ignore[misc]

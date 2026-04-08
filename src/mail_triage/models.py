"""Data models for mail-triage."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Category(str, Enum):
    SECURITY_ALERT = "security-alert"
    INCIDENT = "incident"
    VULNERABILITY = "vulnerability"
    COMPLIANCE = "compliance"
    THREAT_INTEL = "threat-intel"
    NEWSLETTER = "newsletter"
    ANNOUNCEMENT = "announcement"
    DISCUSSION = "discussion"
    OTHER = "other"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EmailData(BaseModel):
    """Parsed email data."""

    subject: str = ""
    sender: str = ""
    date: str = ""
    body: str = ""
    source_file: str = ""


class AnalysisResult(BaseModel):
    """LLM analysis result."""

    category: Category = Category.OTHER
    priority: Priority = Priority.LOW
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    language: str = "en"


class ProcessResult(BaseModel):
    """Result of processing a single email file."""

    source_path: str
    email: EmailData
    analysis: AnalysisResult | None = None
    error: str | None = None
    success: bool = True

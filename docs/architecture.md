# Architecture — mail-triage

This document describes the internal design, decision rationale, and processing
logic of mail-triage. It is intended for developers and operators who need to
understand why the system behaves the way it does.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Execution Modes](#execution-modes)
3. [Processing Pipeline](#processing-pipeline)
4. [Email Parsing](#email-parsing)
5. [LLM Analysis](#llm-analysis)
6. [Slack Notification](#slack-notification)
7. [GCS Object Lifecycle](#gcs-object-lifecycle)
8. [Error Handling Strategy](#error-handling-strategy)
9. [Security Design](#security-design)
10. [Design Decisions](#design-decisions)

---

## System Overview

mail-triage is a batch-oriented email analysis tool designed to run as a
Google Cloud Run Job. It reads email files (`.eml`, `.msg`) from a GCS bucket,
analyzes them using Gemini LLM, and posts structured results to Slack.

```
┌──────────────┐  object.finalize  ┌──────────────────┐
│ GCS          │──── Eventarc ────▶│ Cloud Run Job     │ ← single file mode
│ (inbox/)     │                   │ (mail-triage)     │
└──────────────┘                   └──────┬───────────┘
                                          │
┌──────────────┐  cron (fallback)         │
│ Cloud        │──── trigger ────▶ same job (sweep mode)
│ Scheduler    │                          │
└──────────────┘                   ┌──────┼──────┐
                                   ▼      ▼      ▼
                                  GCS  Gemini  Slack
```

**Why Cloud Run Jobs (not Services)?**
The workload is event-driven batch processing, not persistent request handling.
Jobs scale to zero when idle, cost nothing between executions, and have a
simpler lifecycle model (run → complete → exit).

---

## Execution Modes

### Sweep Mode (default)

Lists all unprocessed files under the `inbox/` prefix and processes them
sequentially. Triggered by Cloud Scheduler on a cron schedule (default: every
30 minutes).

**Why sequential, not parallel?** Slack and Gemini API rate limits make parallel
processing counterproductive. Sequential processing with throttling provides
predictable throughput without hitting rate limits.

### Single File Mode (`--file`)

Processes one specific GCS object by path. Designed for Eventarc triggers that
fire on `google.cloud.storage.object.v1.finalized` events.

**Why both modes?** Eventarc provides near-real-time response for new files.
Cloud Scheduler serves as a safety net to catch files that Eventarc missed
(e.g., during service outages or Pub/Sub delivery failures). When both
trigger for the same file, the second run detects a 404 on download and
skips gracefully.

---

## Processing Pipeline

Each file goes through 5 sequential steps. Each step has independent error
handling to maximize partial success.

```
Download → Parse → Analyze → Notify → Move
   │         │        │         │        │
   ▼         ▼        ▼         ▼        ▼
 fail:     fail:    fail:     fail:    fail:
 abort     abort    continue  leave    leave
                    (notify   in       in
                     failure) inbox    inbox
```

### Step 1: Download

Fetches the blob from GCS. If the blob returns 404 (already processed by a
concurrent run), the file is silently skipped with `success=True`.

### Step 2: Parse

Dispatches to the correct parser based on file extension (`.eml` or `.msg`).
Extracts subject, sender, date, and body text. Body is capped at 1 MB to
prevent OOM on maliciously large emails.

### Step 3: Analyze

Sends email metadata and body to Gemini LLM for classification. If analysis
fails, the pipeline continues — a failure notification is sent to Slack
instead of an analysis notification.

### Step 4: Notify

Posts a Block Kit message to Slack. The email body is attached as a `.body.txt`
file in a thread reply. File upload failure is logged but does not affect the
main notification.

**Critical rule:** If the main Slack notification fails, the file is NOT moved
to `processed/`. It stays in `inbox/` so the next sweep retries it. This
prevents silent notification loss.

### Step 5: Move

Copies the blob from `inbox/` to `processed/`, then deletes the original.
If the delete returns 404 (another run already moved it), the error is
logged as a warning and ignored.

---

## Email Parsing

### EML (RFC 2822)

Parsed using Python's `email` stdlib with `email.policy.default`. This handles:

- RFC 2047 encoded-word headers (e.g., `=?UTF-8?B?...?=` for Japanese subjects)
- Multipart messages (plain text preferred over HTML)
- HTML body stripping via a simple `HTMLParser`-based tag stripper
- Charset auto-detection and UTF-8 conversion

**Why stdlib, not a third-party library?** The stdlib `email` module is
well-maintained, handles edge cases correctly, and has no external dependencies.
For the fields we need (subject, sender, date, body), it is sufficient.

### MSG (OLE2/MAPI)

Parsed using `extract-msg`, which handles the binary OLE2 Compound File format
and MAPI property extraction (Subject, Sender, Date, Body, HTML Body).

**Body size limit:** Both parsers truncate the body to 1 MB. This is a defense
against maliciously crafted emails designed to exhaust container memory. The
LLM prompt further truncates to 3,000 characters, so the 1 MB limit only
affects the Slack body attachment.

---

## LLM Analysis

### Model and Configuration

- **Model:** Gemini 2.5 Flash via Vertex AI (configurable)
- **Temperature:** 0.2 (low randomness for consistent classification)
- **Response format:** `application/json` (enforced via `response_mime_type`)

### Classification Schema

| Field | Values | Purpose |
|-------|--------|---------|
| `category` | security-alert, incident, vulnerability, compliance, threat-intel, newsletter, announcement, discussion, other | Route and prioritize notifications |
| `priority` | high, medium, low | Visual urgency indicator |
| `summary` | Free text (2-3 sentences) | Quick understanding without opening the email |
| `tags` | Up to 5 keywords | Filtering and search |
| `language` | ISO language code | Detect source language |

### Response Validation

LLM output is validated at two levels:

1. **Schema validation:** Unknown categories default to `other`, unknown
   priorities default to `low`, non-list tags are replaced with `[]`,
   tags are capped at 5.

2. **Semantic validation:** If a security-critical category (security-alert,
   incident, vulnerability) is paired with low priority, a warning is logged.
   The LLM judgment is preserved but flagged for human review.

### Retry Strategy

| Error Type | Retryable? | Strategy |
|-----------|------------|----------|
| 429 / resource_exhausted | Yes | Exponential backoff: 5s, 10s, 20s, 40s, 80s, 120s (capped) with ±1s jitter |
| 500 / 503 / unavailable | Yes | Same as above |
| deadline exceeded | Yes | Same as above |
| JSON parse error | No | Immediate failure (bug in prompt or model, not transient) |
| ValueError / TypeError | No | Immediate failure (code-level issue) |

**Why separate parse errors from API errors?** Early versions retried all
errors uniformly. This wasted up to 5 retry attempts (with minutes of delay)
on errors that would never succeed, such as malformed JSON responses.

### Prompt Injection Defense

Email content is untrusted input that could contain adversarial instructions.
Defense is layered:

1. **Nonce-tagged XML boundaries:** Email data is wrapped in
   `<user-data-{random_hex}>...</user-data-{random_hex}>` tags. The random
   nonce prevents attackers from pre-crafting closing tags.

2. **System prompt instruction:** The model is explicitly instructed to treat
   content inside `<user-data-*>` tags as opaque data and never follow
   instructions found within it.

3. **Structured output enforcement:** `response_mime_type="application/json"`
   constrains the model to produce JSON, making free-form instruction following
   harder.

4. **Output validation:** Even if the model produces unexpected values, the
   response parser coerces them to safe defaults (unknown categories → `other`).

**Why nonce tags instead of just a system prompt warning?** System prompt
instructions alone are unreliable — models can be tricked into ignoring them.
The nonce tag creates a clear boundary that the model can reference, and the
randomness prevents pre-crafted escapes.

---

## Slack Notification

### Message Format

Success notifications use Block Kit with 5 blocks:

1. **Header:** Category emoji + subject (plain_text, not mrkdwn)
2. **Section:** Category and priority with emojis
3. **Section:** Sender and date
4. **Section:** LLM-generated summary
5. **Context:** Tags as inline code

The email body is posted as a `.body.txt` file attachment in a thread reply,
keeping the main channel clean.

### Rate Limit Handling

Slack's API has strict rate limits (Tier 3: ~50 req/min for `chat.postMessage`).
Two mechanisms prevent hitting them:

1. **SDK-level retry:** `RateLimitErrorRetryHandler` automatically retries on
   429 responses, respecting the `Retry-After` header. Up to 3 retries.

2. **Application-level throttle:** A minimum 1.5-second interval between API
   calls prevents burst traffic during batch processing.

### mrkdwn Escaping

Untrusted text (email subjects, sender addresses, error messages) is escaped
before embedding in mrkdwn fields. Special characters (`*_~\`[]|`) are
backslash-escaped to prevent formatting injection. Header blocks use
`plain_text` type, which is not affected.

### URL Defanging

The LLM is instructed to defang all URLs and domain names in summaries
(e.g., `example.com` → `example[.]com`). This prevents Slack from creating
clickable links to potentially malicious domains.

---

## GCS Object Lifecycle

```
Upload           Processing        Complete
  │                 │                 │
  ▼                 ▼                 ▼
inbox/file.eml → [download] → processed/file.eml
                    │
                  (copy + delete)
```

### Why Copy-Then-Delete (not Rename)?

GCS does not support atomic rename. The copy-then-delete pattern is the
standard approach. The 404-safe delete handles the race condition when
two runs process the same file concurrently.

### Concurrent Execution Safety

| Scenario | Behavior |
|----------|----------|
| Eventarc + Scheduler process same file | First run succeeds. Second run gets 404 on download, skips. |
| Two Scheduler runs overlap | Same as above. |
| Crash after copy, before delete | File exists in both `inbox/` and `processed/`. Next run downloads from `inbox/`, copy to `processed/` overwrites, delete completes. No data loss, one duplicate Slack notification possible. |

---

## Error Handling Strategy

The system follows a "fail open for analysis, fail closed for notification"
principle:

- **Analysis failure → continue:** The file is processed and Slack receives a
  failure notification. The operator knows the file exists but analysis failed.
- **Notification failure → retry:** The file stays in `inbox/` so the next
  sweep retries. No silent notification loss.
- **File upload failure → warn:** The main message already posted. A warning
  log is generated but the pipeline continues.

This design prioritizes **notification reliability** over analysis completeness.
A missing analysis can be re-run manually; a missing notification may never be
noticed.

---

## Security Design

### Credential Management

| Credential | Storage | Access |
|-----------|---------|--------|
| Slack bot token | GCP Secret Manager | Injected as Cloud Run secret |
| GCP service account | Managed by GCP IAM | ADC (no key files) |
| Gemini API | Vertex AI (project-level) | Service account IAM binding |

No credentials are ever stored in code, config files, or container images.

### Container Hardening

- **Non-root user:** The Docker image runs as `appuser`, not root.
- **Minimal base image:** `python:3.11-slim` with no unnecessary packages.
- **No shell access needed:** The entrypoint runs the CLI directly.

### Input Validation Boundaries

| Boundary | Validation |
|----------|-----------|
| GCS → Parser | File extension check, body size cap (1 MB) |
| Email content → LLM | Nonce-tagged XML wrapping, body truncation (3,000 chars) |
| LLM output → Application | JSON schema validation, enum coercion, tag count limit |
| Email metadata → Slack | mrkdwn special character escaping |
| Error messages → Slack | mrkdwn escaping + truncation (500 chars) |

---

## Design Decisions

### Why Python (not Go)?

The organization primarily uses Go, but mail-triage chose Python because:

1. **Email parsing:** Python's `email` stdlib handles RFC 2822 comprehensively.
   Go's `net/mail` is functional but less forgiving of malformed emails.
2. **MSG parsing:** `extract-msg` is the most mature MSG parser available.
   Go has no equivalent library.
3. **SDK availability:** `google-genai`, `google-cloud-storage`, and `slack-sdk`
   are all first-class Python libraries.
4. **Operational simplicity:** All dependencies in one language, one container.

### Why Vertex AI (not Gemini API Key)?

- Service account authentication via ADC — no API key rotation needed.
- Project-level quota management.
- Consistent with other org tools (`ai-ir2`, `news-collector`).

### Why google-genai SDK (not vertexai SDK)?

The `vertexai` SDK is deprecated. The `google-genai` SDK is the recommended
replacement per Google's migration guide and org conventions.

### Why Not Eventarc-Only (no Scheduler)?

Eventarc relies on Pub/Sub delivery. In practice, messages can be delayed or
dropped during:
- GCP service incidents
- Pub/Sub subscription expiration
- Eventarc trigger misconfiguration

The Cloud Scheduler sweep provides a reliable fallback that catches any files
Eventarc missed. The cost of a redundant sweep (listing an empty prefix) is
negligible.

### Why Move Files (not Mark with Metadata)?

GCS custom metadata would require listing all objects and checking each one's
metadata on every sweep — O(n) API calls per sweep. Moving to a separate
prefix makes listing unprocessed files a single O(1) `list_blobs()` call
with prefix filtering.

### Why 1.5s Slack Throttle (not Exact Rate)?

Slack's Tier 3 limit is ~50 req/min (1.2s/req), but rate limits are per-app
across all channels and methods. A 1.5s interval provides margin for the
file upload that follows each message. The SDK's `RateLimitErrorRetryHandler`
catches any remaining burst violations.

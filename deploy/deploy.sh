#!/usr/bin/env bash
# deploy.sh — One-liner deployment for mail-triage on GCP
#
# Sets up: Artifact Registry, Cloud Run Job, Eventarc trigger,
#          Cloud Scheduler, IAM bindings, and GCS bucket.
#
# Usage:
#   ./deploy/deploy.sh <config-file>
#
# Config file format (shell variables):
#   PROJECT_ID=my-project
#   REGION=us-central1
#   BUCKET_NAME=my-email-bucket
#   SLACK_CHANNEL=#mail-digest
#   ...
#
# See deploy/deploy.env.template for all variables.

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────
log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;33m── %s ──\033[0m\n' "$*"; }

# ── Load config ──────────────────────────────────────────────────────
CONFIG_FILE="${1:-}"
[[ -z "$CONFIG_FILE" ]] && err "Usage: $0 <config-file>"
[[ -f "$CONFIG_FILE" ]] || err "Config file not found: $CONFIG_FILE"
# shellcheck source=/dev/null
source "$CONFIG_FILE"

# ── Required variables ───────────────────────────────────────────────
: "${PROJECT_ID:?}"
: "${REGION:?}"
: "${BUCKET_NAME:?}"
: "${REPO_NAME:=mail-triage}"
: "${JOB_NAME:=mail-triage}"
: "${SA_NAME:=mail-triage-sa}"
: "${SLACK_CHANNEL:?}"
: "${INPUT_PREFIX:=inbox/}"
: "${DONE_PREFIX:=processed/}"
: "${GEMINI_MODEL:=gemini-2.5-flash}"
: "${SCHEDULER_CRON:=*/30 * * * *}"
: "${SCHEDULER_TZ:=Asia/Tokyo}"
: "${SUMMARY_LANG:=}"
: "${JOB_TIMEOUT:=600}"
: "${JOB_MEMORY:=512Mi}"
: "${JOB_CPU:=1}"

_IAM_DOMAIN="iam.gserviceaccount.com"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.${_IAM_DOMAIN}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${JOB_NAME}:latest"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

log "Project:  $PROJECT_ID ($PROJECT_NUMBER)"
log "Region:   $REGION"
log "Bucket:   $BUCKET_NAME"
log "Image:    $IMAGE"

# ── Enable APIs ──────────────────────────────────────────────────────
step "Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  eventarc.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT_ID" --quiet

# ── Service Account ─────────────────────────────────────────────────
step "Setting up service account"
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="mail-triage service account" \
    --project="$PROJECT_ID"
  log "Created service account: $SA_EMAIL"
else
  log "Service account already exists: $SA_EMAIL"
fi

# IAM roles for the service account
ROLES=(
  "roles/storage.objectAdmin"
  "roles/aiplatform.user"
  "roles/secretmanager.secretAccessor"
  "roles/run.invoker"
  "roles/logging.logWriter"
)
for role in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet &>/dev/null
done
log "IAM roles assigned"

# ── GCS Bucket ───────────────────────────────────────────────────────
step "Setting up GCS bucket"
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="$PROJECT_ID" &>/dev/null; then
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access
  log "Created bucket: gs://${BUCKET_NAME}"
else
  log "Bucket already exists: gs://${BUCKET_NAME}"
fi

# ── Artifact Registry ───────────────────────────────────────────────
step "Setting up Artifact Registry"
if ! gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID"
  log "Created repository: $REPO_NAME"
else
  log "Repository already exists: $REPO_NAME"
fi

# ── Build & Push Container ──────────────────────────────────────────
step "Building and pushing container"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build -t "$IMAGE" -f deploy/Dockerfile .
docker push "$IMAGE"
log "Pushed: $IMAGE"

# ── Slack Bot Token Secret ───────────────────────────────────────────
step "Setting up Slack bot token secret"
SECRET_NAME="mail-triage-slack-bot-token"
if ! gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
  log "Creating secret: $SECRET_NAME"
  log "You will need to add the secret value manually:"
  log "  echo -n 'YOUR_SLACK_BOT_TOKEN' | gcloud secrets versions add $SECRET_NAME --data-file=- --project=$PROJECT_ID"
  gcloud secrets create "$SECRET_NAME" --project="$PROJECT_ID" --replication-policy=automatic
else
  log "Secret already exists: $SECRET_NAME"
fi

# ── Cloud Run Job ────────────────────────────────────────────────────
step "Deploying Cloud Run Job"

ENV_VARS="MAIL_TRIAGE_BUCKET=${BUCKET_NAME}"
ENV_VARS="${ENV_VARS},MAIL_TRIAGE_PREFIX=${INPUT_PREFIX}"
ENV_VARS="${ENV_VARS},MAIL_TRIAGE_DONE_PREFIX=${DONE_PREFIX}"
ENV_VARS="${ENV_VARS},MAIL_TRIAGE_PROJECT=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},MAIL_TRIAGE_LOCATION=${REGION}"
ENV_VARS="${ENV_VARS},MAIL_TRIAGE_MODEL=${GEMINI_MODEL}"
ENV_VARS="${ENV_VARS},SLACK_CHANNEL=${SLACK_CHANNEL}"
[[ -n "$SUMMARY_LANG" ]] && ENV_VARS="${ENV_VARS},SUMMARY_LANG=${SUMMARY_LANG}"

if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  gcloud run jobs update "$JOB_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --set-env-vars="$ENV_VARS" \
    --set-secrets="SLACK_BOT_TOKEN=${SECRET_NAME}:latest" \
    --memory="$JOB_MEMORY" \
    --cpu="$JOB_CPU" \
    --task-timeout="$JOB_TIMEOUT" \
    --quiet
  log "Updated job: $JOB_NAME"
else
  gcloud run jobs create "$JOB_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SA_EMAIL" \
    --set-env-vars="$ENV_VARS" \
    --set-secrets="SLACK_BOT_TOKEN=${SECRET_NAME}:latest" \
    --memory="$JOB_MEMORY" \
    --cpu="$JOB_CPU" \
    --task-timeout="$JOB_TIMEOUT" \
    --quiet
  log "Created job: $JOB_NAME"
fi

# ── Eventarc Trigger (GCS object finalize) ───────────────────────────
step "Setting up Eventarc trigger"

# Grant Eventarc permissions to GCS service account
GCS_SA="service-${PROJECT_NUMBER}@gs-project-accounts.${_IAM_DOMAIN}"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${GCS_SA}" \
  --role="roles/pubsub.publisher" \
  --condition=None \
  --quiet &>/dev/null

TRIGGER_NAME="${JOB_NAME}-gcs-trigger"
if gcloud eventarc triggers describe "$TRIGGER_NAME" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  log "Eventarc trigger already exists: $TRIGGER_NAME"
else
  gcloud eventarc triggers create "$TRIGGER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --destination-run-job="$JOB_NAME" \
    --destination-run-region="$REGION" \
    --event-filters="type=google.cloud.storage.object.v1.finalized" \
    --event-filters="bucket=${BUCKET_NAME}" \
    --service-account="$SA_EMAIL"
  log "Created Eventarc trigger: $TRIGGER_NAME"
fi

# ── Cloud Scheduler (sweep fallback) ────────────────────────────────
step "Setting up Cloud Scheduler"

SCHEDULER_NAME="${JOB_NAME}-sweep"
SCHEDULER_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "$SCHEDULER_NAME" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  gcloud scheduler jobs update http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULER_CRON" \
    --time-zone="$SCHEDULER_TZ" \
    --uri="$SCHEDULER_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" \
    --quiet
  log "Updated scheduler: $SCHEDULER_NAME"
else
  gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULER_CRON" \
    --time-zone="$SCHEDULER_TZ" \
    --uri="$SCHEDULER_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SA_EMAIL" \
    --quiet
  log "Created scheduler: $SCHEDULER_NAME"
fi

# ── Summary ──────────────────────────────────────────────────────────
step "Deployment complete"
log ""
log "Resources created:"
log "  Bucket:       gs://${BUCKET_NAME}"
log "  Job:          ${JOB_NAME} (${REGION})"
log "  Eventarc:     ${TRIGGER_NAME} (on object finalize)"
log "  Scheduler:    ${SCHEDULER_NAME} (${SCHEDULER_CRON})"
log "  SA:           ${SA_EMAIL}"
log ""
log "Next steps:"
log "  1. Add Slack bot token to Secret Manager:"
log "     echo -n 'YOUR_SLACK_BOT_TOKEN' | gcloud secrets versions add ${SECRET_NAME} --data-file=- --project=${PROJECT_ID}"
log "  2. Upload an email file to test:"
log "     gcloud storage cp test.eml gs://${BUCKET_NAME}/${INPUT_PREFIX}"
log "  3. Check job execution:"
log "     gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION} --project=${PROJECT_ID}"

-- Reference schema. Alembic migrations become executable source after implementation.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE DOMAIN sha256_hex AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');

CREATE TYPE source_visibility AS ENUM ('PUBLIC', 'INTERNAL', 'PRIVATE');
CREATE TYPE claim_class AS ENUM ('COMMERCIAL_VERIFIED','PORTFOLIO_VERIFIED','CERTIFICATE_VERIFIED','PUBLIC_SOURCE_VERIFIED','PERSONAL_OBSERVATION','UNVERIFIED');
CREATE TYPE qa_result AS ENUM ('PASS','PASS_WITH_WARNINGS','FAIL');
CREATE TYPE integration_status AS ENUM ('DISCONNECTED','CONNECTED','EXPIRING','AUTH_REQUIRED','REVOKED','MISCONFIGURED');
CREATE TYPE draft_status AS ENUM ('GENERATING','GENERATION_FAILED','DRAFTED','QA_RUNNING','QA_FAILED','AWAITING_APPROVAL','APPROVED','REJECTED','INVALIDATED');
CREATE TYPE asset_status AS ENUM ('CREATED','VALIDATED','UPLOAD_PENDING','UPLOADING','PROCESSING','AVAILABLE','UPLOAD_FAILED','PROCESSING_FAILED');
CREATE TYPE publication_status AS ENUM ('CREATED','SCHEDULED','PUBLISHING','PUBLISHED','AUTH_REQUIRED','RATE_LIMITED','VALIDATION_FAILED','ASSET_FAILED','PUBLISH_FAILED','PUBLISH_UNCERTAIN','CANCELLED');
CREATE TYPE attempt_phase AS ENUM ('ACQUIRED','PREPARED','FINAL_REQUEST_STARTED','FINAL_RESPONSE_RECEIVED','COMPLETED');

CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_type text NOT NULL,
  canonical_url text, title text, raw_content text, content_hash sha256_hex NOT NULL,
  trust_level smallint NOT NULL DEFAULT 1 CHECK (trust_level BETWEEN 0 AND 5),
  visibility source_visibility NOT NULL, captured_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb, UNIQUE (source_type, content_hash)
);

CREATE TABLE content_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), topic text NOT NULL, pillar text NOT NULL,
  status text NOT NULL, primary_source_id uuid REFERENCES sources(id),
  scores jsonb NOT NULL DEFAULT '{}'::jsonb, risk_notes jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), claim_key text NOT NULL UNIQUE,
  claim_class claim_class NOT NULL, claim_ru text, claim_en text,
  source_reference text NOT NULL, allowed_public boolean NOT NULL DEFAULT false,
  allowed_wording jsonb NOT NULL DEFAULT '[]'::jsonb,
  forbidden_inferences jsonb NOT NULL DEFAULT '[]'::jsonb,
  confidence numeric(3,2) NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
  active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), content_item_id uuid NOT NULL REFERENCES content_items(id),
  version integer NOT NULL, language text NOT NULL CHECK (language IN ('ru','en')),
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (content_item_id, version)
);

CREATE TABLE evidence_pack_claims (
  evidence_pack_id uuid NOT NULL REFERENCES evidence_packs(id) ON DELETE CASCADE,
  evidence_item_id uuid NOT NULL REFERENCES evidence_items(id),
  PRIMARY KEY (evidence_pack_id, evidence_item_id)
);

CREATE TABLE evidence_pack_forbidden_claims (
  evidence_pack_id uuid NOT NULL REFERENCES evidence_packs(id) ON DELETE CASCADE,
  claim_key text NOT NULL,
  PRIMARY KEY (evidence_pack_id, claim_key)
);

CREATE TABLE evidence_pack_sources (
  evidence_pack_id uuid NOT NULL REFERENCES evidence_packs(id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES sources(id),
  PRIMARY KEY (evidence_pack_id, source_id)
);

CREATE TABLE draft_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), content_item_id uuid NOT NULL REFERENCES content_items(id),
  evidence_pack_id uuid NOT NULL REFERENCES evidence_packs(id), version integer NOT NULL,
  parent_version_id uuid REFERENCES draft_versions(id), language text NOT NULL CHECK (language IN ('ru','en')),
  pillar text NOT NULL, full_text text NOT NULL CHECK (length(btrim(full_text)) > 0),
  structured_content jsonb NOT NULL, text_hash sha256_hex NOT NULL, status draft_status NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (content_item_id, version)
);

CREATE TABLE draft_version_claims (
  draft_version_id uuid NOT NULL REFERENCES draft_versions(id) ON DELETE CASCADE,
  evidence_item_id uuid NOT NULL REFERENCES evidence_items(id),
  PRIMARY KEY (draft_version_id, evidence_item_id)
);

CREATE TABLE qa_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), draft_version_id uuid NOT NULL REFERENCES draft_versions(id),
  deterministic_result qa_result NOT NULL, deterministic_report jsonb NOT NULL,
  llm_result qa_result, llm_report jsonb, final_result qa_result NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), asset_type text NOT NULL CHECK (asset_type IN ('IMAGE','DOCUMENT')),
  mime_type text NOT NULL, storage_key text NOT NULL UNIQUE, checksum_sha256 sha256_hex NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0), alt_text text, status asset_status NOT NULL,
  linkedin_media_urn text, upload_url_ciphertext text, upload_url_expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), draft_version_id uuid NOT NULL REFERENCES draft_versions(id),
  asset_id uuid REFERENCES assets(id), approval_fingerprint sha256_hex NOT NULL UNIQUE,
  approved_by text NOT NULL, warnings_accepted jsonb NOT NULL DEFAULT '[]'::jsonb,
  approved_at timestamptz NOT NULL DEFAULT now(), invalidated_at timestamptz, invalidation_reason text
);

CREATE TABLE linkedin_integrations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_key text NOT NULL UNIQUE,
  member_subject text, author_urn text, access_token_ciphertext text,
  token_expires_at timestamptz, status integration_status NOT NULL,
  api_version text NOT NULL, capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_success_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    status IN ('DISCONNECTED','MISCONFIGURED')
    OR (
      member_subject IS NOT NULL
      AND author_urn IS NOT NULL
      AND access_token_ciphertext IS NOT NULL
      AND token_expires_at IS NOT NULL
    )
  )
);

CREATE TABLE oauth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), state_hash text NOT NULL UNIQUE,
  redirect_after text, expires_at timestamptz NOT NULL, consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE publication_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), approval_id uuid NOT NULL REFERENCES approvals(id),
  integration_id uuid NOT NULL REFERENCES linkedin_integrations(id), scheduled_at timestamptz NOT NULL,
  visibility text NOT NULL DEFAULT 'PUBLIC' CHECK (visibility = 'PUBLIC'),
  publication_fingerprint sha256_hex NOT NULL,
  status publication_status NOT NULL, next_eligible_at timestamptz, locked_at timestamptz,
  locked_by text, attempt_count integer NOT NULL DEFAULT 0, linkedin_post_urn text,
  published_at timestamptz, last_error_code text, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (
    (status = 'PUBLISHED' AND linkedin_post_urn IS NOT NULL AND published_at IS NOT NULL)
    OR status <> 'PUBLISHED'
  )
);
CREATE UNIQUE INDEX uq_active_publication_fingerprint
  ON publication_jobs(publication_fingerprint)
  WHERE status IN (
    'CREATED','SCHEDULED','PUBLISHING','AUTH_REQUIRED','RATE_LIMITED','PUBLISH_UNCERTAIN'
  );
CREATE INDEX ix_publication_due ON publication_jobs(status, scheduled_at, next_eligible_at);

CREATE TABLE publication_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), publication_job_id uuid NOT NULL REFERENCES publication_jobs(id),
  attempt_number integer NOT NULL CHECK (attempt_number > 0), phase attempt_phase NOT NULL,
  request_fingerprint sha256_hex NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, http_status integer,
  response_post_urn text, safe_error_code text, safe_diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,
  retry_allowed boolean NOT NULL DEFAULT false, UNIQUE (publication_job_id, attempt_number)
);
CREATE UNIQUE INDEX uq_one_incomplete_publication_attempt
  ON publication_attempts(publication_job_id)
  WHERE finished_at IS NULL;

CREATE TABLE metric_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), publication_job_id uuid NOT NULL REFERENCES publication_jobs(id),
  source text NOT NULL CHECK (source IN ('MANUAL','LINKEDIN_API')),
  captured_at timestamptz NOT NULL DEFAULT now(), metrics jsonb NOT NULL
);

CREATE TABLE audit_events (
  id bigserial PRIMARY KEY, event_type text NOT NULL, entity_type text NOT NULL,
  entity_id text NOT NULL, actor text NOT NULL, correlation_id text,
  safe_payload jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_entity ON audit_events(entity_type, entity_id, created_at);

CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), event_type text NOT NULL,
  aggregate_type text NOT NULL, aggregate_id text NOT NULL, payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), available_at timestamptz NOT NULL DEFAULT now(),
  acknowledged_at timestamptz, attempt_count integer NOT NULL DEFAULT 0
);
CREATE INDEX ix_outbox_pending ON outbox_events(acknowledged_at, available_at);

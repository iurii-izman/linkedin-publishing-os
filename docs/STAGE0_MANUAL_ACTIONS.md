# Stage 0 Owner Manual Actions

Access date for the referenced LinkedIn documentation: **23 July 2026**.

Do not paste a client secret, access token, authorization code or encryption key into
chat, an issue, a Markdown file or a terminal transcript committed to Git.

## 1. Create and configure the LinkedIn application

1. Open [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps).
2. Create an application owned by an eligible LinkedIn Page. Complete LinkedIn's
   verification steps; these cannot be automated by this repository.
3. On **Products**, request/enable:
   - **Sign in with LinkedIn using OpenID Connect**;
   - **Share on LinkedIn**.
4. On **Auth**, confirm the available scopes include exactly those needed by the spike:
   `openid`, `profile`, `w_member_social`. Do not request `email`.
5. Add the exact HTTPS redirect URI:
   `https://<your-public-stage0-host>/v1/oauth/linkedin/callback`.
6. Record only product names, scope names and screenshots with every credential area
   cropped or redacted.

Stop with `NO_GO` if Share on LinkedIn or `w_member_social` is unavailable. Do not use
browser automation as a substitute.

## 2. Prepare local configuration

```powershell
Copy-Item .env.example .env
uv sync --frozen --dev
```

Generate a Fernet key (32 random bytes encoded with URL-safe base64) using a local
password/secret manager without recording it in terminal history. Put it and the Developer Portal values directly in the local
`.env`. Never send them through chat. Set:

- `APP_PUBLIC_URL`;
- `LINKEDIN_CLIENT_ID`;
- `LINKEDIN_CLIENT_SECRET`;
- `LINKEDIN_REDIRECT_URI`;
- `TOKEN_ENCRYPTION_KEY`;
- `STAGE0_OWNER_KEY` (a separate random value of at least 32 characters);
- `LINKEDIN_API_VERSION=202607`.

The public URL must terminate HTTPS and route to the local service. Tunnel selection
and account setup are owner infrastructure choices; no LinkedIn browser automation is
included.

## 3. Start OAuth

```powershell
uv run uvicorn publisher_api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Access logging is disabled because the OAuth callback query contains a short-lived
authorization code and state. Do not enable raw request-target logging for the spike.

In a second terminal, read the owner key without echoing it:

```powershell
$secureOwnerKey = Read-Host "Stage 0 owner key" -AsSecureString
$stage0OwnerKey = [System.Net.NetworkCredential]::new("", $secureOwnerKey).Password
$headers = @{"X-Stage0-Owner-Key" = $stage0OwnerKey}
Invoke-RestMethod -Method Post -Headers $headers -Uri http://127.0.0.1:8000/v1/oauth/linkedin/start
Remove-Variable secureOwnerKey, stage0OwnerKey, headers
```

Open the returned `authorization_url` yourself. LinkedIn should redirect to the
configured callback. Expected safe output contains:

- `status=connected_for_stage0`;
- expiry time;
- granted scope names;
- a person URN candidate;
- `requires_live_author_validation=true`.

It must not contain any token. The encrypted local record is
`.stage0/linkedin-connection.enc`.

## 4. Dry preparation

Use the callback's safe person URN:

```powershell
uv run lpos-stage0 prepare-text --author-urn "urn:li:person:<observed-id>"
uv run lpos-stage0 prepare-image --author-urn "urn:li:person:<observed-id>" --image .\synthetic-stage0.png
```

These commands print redacted request plans and make no LinkedIn call.

## 5. Controlled text publication

Review the fixed synthetic text, then run exactly once:

```powershell
uv run lpos-stage0 publish-text --confirm-live-publish
```

Expected output is HTTP 201 and a `urn:li:share:*` or `urn:li:ugcPost:*` value. If the
command reports `UNCERTAIN`, do not rerun it. Inspect the LinkedIn profile manually.

## 6. Controlled image publication

Create a public-safe JPEG or PNG containing only synthetic test graphics. Then:

```powershell
uv run lpos-stage0 publish-image --image .\synthetic-stage0.png --alt-text "Synthetic Stage 0 API test image" --confirm-live-publish
```

The harness initializes the image, uploads only to the validated
`https://www.linkedin.com/dms-uploads/` host, waits a bounded time for `AVAILABLE`,
and performs one final post request. It never retries the final request.

## 7. Record sanitized evidence

Update `docs/feasibility_report.md` with:

1. product and scope names;
2. observed `expires_in` in seconds, not a token;
3. whether OIDC `sub` formed the accepted person URN;
4. endpoint and `Linkedin-Version`;
5. HTTP statuses and post/image URNs;
6. safe error codes;
7. UTC observation times.

Do not copy request headers, query strings, upload URLs, auth codes or raw error
bodies. Manually verify each post on the profile and delete test posts using
LinkedIn's native UI after recording the URNs and outcome.

## 8. Troubleshooting

| Result | Action |
|---|---|
| OAuth 400/401 | Recheck exact redirect URI, code freshness, client ID and state; start a new flow. |
| 401 from API | Reauthorize; do not recreate scheduled work. |
| 403 | Confirm product, `w_member_social`, author URN and app ownership; stop for a decision. |
| 409 | Record the response status; do not switch endpoints or retry blindly. |
| 426 | Stop, verify a supported version in official docs, update config and rerun mock checks first. |
| 429 | Record `Retry-After` if present and stop the smoke; do not loop. |
| 500/503 | Do not retry a final post automatically; manually inspect the profile. |
| timeout/connection loss after final request | Treat as `PUBLISH_UNCERTAIN`; reconcile manually. |
| 201 without `x-restli-id` | Treat as uncertain and inspect the profile manually. |

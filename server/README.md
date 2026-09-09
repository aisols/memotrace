# MemoTrace ingestion server

Working, **unreleased** first ingestion slice: Go **1.26.4**, PostgreSQL **15**,
private Linux filesystem originals, TLS-only CLI/server, and contract **0.1.0**.
Original bytes, immutable metadata, and one initial **pending** processing job are
persisted. Inference, search, queue consumers and phone eviction are later work.

## Independent build and verification

Run from this directory; builds/tests need no sibling sources or parent configuration.

```sh
go build -trimpath -o /tmp/memotrace ./cmd/memotrace
go test ./...                 # unit/schema checks; PostgreSQL tests explicitly skip
bash scripts/verify.sh       # required full verification, including PostgreSQL
docker build -t memotrace-server:local .
```

Full verification requires Linux, Go 1.26.4, Python 3 and Docker. It creates its
**own uniquely named disposable PostgreSQL container**, random credential,
ephemeral loopback port and identity-checked trap cleanup. It never reuses an
existing container/database. The locally inspected PostgreSQL-15 image is pinned:
`postgres@sha256:74e110c41804365e3915fcc09d5e7a1eff50161aaa94d5da0e58e0cd75ae509c`.
No host psql, pgvector, private fixtures or cloud credentials are needed.
See [quality gates](docs/quality.md).

## Database provisioning

Use a dedicated database with separate administrative/migration and runtime roles.
The local admin owns the schema, tables and security-definer functions. Runtime
must not own the database/schema/tables or inherit the admin role. Startup rejects
superuser, BYPASSRLS, CREATEROLE, CREATEDB, privileged file/all-data roles, inherited
table/schema ownership, missing content RLS and direct bootstrap-table privileges.

For your explicitly selected operator-managed PostgreSQL deployment:

```sh
docker exec -it "$PG_CONTAINER" psql -U postgres -d postgres
```

Provision interactively; `\password` keeps passwords out of checked-in SQL/history:

```sql
CREATE ROLE memotrace_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
\password memotrace_admin
CREATE ROLE memotrace_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
\password memotrace_runtime
CREATE DATABASE memotrace OWNER memotrace_admin;
REVOKE ALL ON DATABASE memotrace FROM PUBLIC;
GRANT CONNECT ON DATABASE memotrace TO memotrace_admin, memotrace_runtime;
\connect memotrace
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

Provide **`MEMOTRACE_ADMIN_DSN`** securely to local administrative commands and
**`MEMOTRACE_DSN`** to the service. Use a trusted local Unix socket or verified
PostgreSQL TLS (`sslmode=verify-full` with an operator-provisioned trust root).
Only the disposable loopback tests use `sslmode=disable`. DSNs must select this
dedicated database; do not log them or pass secrets in command arguments.

```sh
/tmp/memotrace migrate --runtime-role memotrace_runtime
/tmp/memotrace create-archive
```

Archive creation emits `owner_id` and `archive_id` JSON. Migration is transactional,
advisory-lock serialized, repeatable at version 1, and fails on unsupported versions.
This unreleased initial migration is not an upgrade path for independently modified
schemas. Role creation/passwords remain privileged local PostgreSQL operations.

## TLS and trusted invitation bootstrap

Provision an encrypted volume, then pre-create a private absolute data root on it,
owned by the service UID and mode `0700`. The root/parent directories are trusted;
the server does not recursively create an arbitrary data-root path.

Use an operator-provisioned certificate/key, or generate a local certificate with
OpenSSL. Create a **new** directory so existing keys cannot be clobbered:

```sh
umask 077
TLS_DIR=/srv/memotrace/tls-bootstrap-1
mkdir "$TLS_DIR"  # intentionally fails if this bootstrap directory exists
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 365 \
  -subj /CN=localhost -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  -keyout "$TLS_DIR/key.pem" -out "$TLS_DIR/cert.pem"
openssl x509 -in "$TLS_DIR/cert.pem" -outform DER | openssl dgst -sha256
```

For LAN use, include the actual DNS name/IP in SAN. Obtain the leaf DER SHA-256 pin
from this **trusted local certificate** and transport it out of band. Fetching an
untrusted network certificate and trusting its own fingerprint establishes no trust.
Start with only the runtime DSN in the service environment:

```sh
/tmp/memotrace serve --data-root /srv/memotrace/data \
  --cert "$TLS_DIR/cert.pem" --key "$TLS_DIR/key.pem"
```

Default: `127.0.0.1:8443`; LAN requires explicit `--listen 0.0.0.0:8443` or a selected
interface. No plaintext mode. Minimum TLS 1.2; key must be a private regular file,
mode `0600` or stricter. With the live TLS service available, issue an invitation
from a local shell holding the admin DSN:

```sh
/tmp/memotrace invite --archive ARCHIVE_UUID --server-url https://localhost:8443 \
  --cert "$TLS_DIR/cert.pem" --expected-pin TRUSTED_64_HEX_SHA256 --ttl 10m
/tmp/memotrace revoke-device --device DEVICE_UUID
```

`invite` verifies origin syntax/port, certificate name/validity, the explicitly
supplied out-of-band pin, **and the live server's normally verified TLS leaf**.
The exact origin must start with lower-case `https://`; an explicit port has 1–5
digits (leading zeros allowed) and numeric value 1–65535. Accepted origins are emitted
unchanged. Invitation JSON is suitable for trusted manual/QR transport. TTL is a
whole number of seconds from **1 through 600**, default 600; fractional-second,
zero, negative and longer TTLs are rejected before database access. Expiry retains
fractional time at PostgreSQL microsecond precision and is emitted as RFC3339 UTC
with the same persisted instant. The CLI checks it is still future before successful
output; ordinary delivery/use delays can subsequently expire an invitation.
Credentials are 32 random bytes, base64url without padding; only hashes
are stored. Raw credentials appear only in direct CLI output or pairing response.
Protect captured output. A lost successful pairing response requires local revocation
and re-enrollment. Certificate renewal/rotation requires trusted re-bootstrap.

## HTTP surface

| Method/path | Result |
| --- | --- |
| `GET /healthz` | Process liveness and contract version, no archive-health assertion |
| `POST /v1/pairing/redeem` | One-time invitation redemption and archive-scoped device |
| `POST /v1/archives/{archive_id}/frames` | Transactional registration of 1–100 immutable metadata records |
| `PUT /v1/archives/{archive_id}/frames/{frame_id}/original` | Full JPEG verification/publication and stable receipt |
| `GET .../{frame_id}/receipt` | Historical durable receipt, including lost ACK recovery |
| `GET .../{frame_id}/original` | Exact verified bytes or fail-closed integrity error |

Other `/v1` operations require `Authorization: Bearer DEVICE_TOKEN`. Other archives
are 404; missing/invalid/revoked credentials are 401. Authorized devices in the same
archive can resume records while preserving the original registering device.
The auth scheme is case-insensitive (`Bearer`, `bearer`, `BEARER`), followed by one
or more ASCII spaces per RFC 6750 §2.1; the credential bytes remain exact. Tabs are
not separators, trailing credential whitespace and repeated Authorization headers
are rejected. Every protected
archive-route 401 includes `WWW-Authenticate: Bearer realm="memotrace"`. Redemption
401 instead includes `WWW-Authenticate: MemoTraceInvitation realm="memotrace-pairing"`:
this application-specific challenge requests `invitation_token` in the JSON body,
not a device bearer credential.
Missing/null optional legacy/profile fields normalize identically. Batch order is
preserved, duplicate IDs rejected, differing immutable metadata returns 409.

Request time is not shutter time; sessionless elapsed time establishes no shared
timeline; saved time can refer to recovery. Absent fields are never fabricated.
The canonical [schema](internal/contract/snapshot/schemas/ingestion.schema.json) and
[OpenAPI](internal/contract/snapshot/openapi/ingestion.json) define exact fields,
bounds and errors. JSON is limited to 1 MiB, originals to 16 MiB. Unknown/case-aliased/
duplicate members and malformed required fields are rejected; mathematical integers
normalize without floating-point rounding. Errors are generic; wrong methods use
405 `invalid_request`. Handler responses carry `no-store` and `nosniff`.
All JSON strings, including property names, must contain valid Unicode scalar values;
unpaired UTF-16 surrogate escapes are rejected before Go's lossy JSON decoder.
`device_name`, `profile.id` and `capture_settings` additionally exclude U+0000 (NUL),
as defined by the canonical contract. Text is never stripped, replaced or Unicode-
normalized. Genuine U+FFFD, astral characters (raw UTF-8 or paired escapes), and
literal escaped backslashes remain valid and distinct immutable text.

## Deployment and limitations

Use **one process and one data root per database**. A Linux flock held for the
process lifetime prevents cooperating processes sharing one root. Startup recovers
pending published originals before opening TLS. Unknown/staging entries are preserved
and counted; corrupt known pending originals block startup for operator investigation.
Do not remove the lockfile while serving. See [storage details](docs/storage.md).

The container runs as UID/GID `10001`, with digest-pinned bases. Mount pre-created
private `/data` owned by UID 10001 and read-only `/tls` with a readable private key.
Provide the runtime DSN through secure deployment configuration. For container
networking explicitly add `--listen 0.0.0.0:8443` to `serve`; the loopback default
also applies inside containers. Compose/assembly remains deployment-owned.

Receipts mean historical durable commit under declared Linux/filesystem/PG settings,
not ML completion, perpetual availability, backup proof or phone-eviction permission.
Original reads verify current bytes; historical receipts survive later corruption.
Revocation is rechecked after upload streaming; authorized in-flight downloads may finish.

At-rest protection relies on **operator-provisioned encrypted volumes/backups**.
The application does not implement E2EE, attest encryption or protect against the
trusted root/database operator. Back up encryption recovery keys and certificate
keys separately and securely; resetting credentials cannot recover lost encryption
keys. Back up PostgreSQL and originals coherently with the service stopped, and
prove restoration on a clean node before relying on retention/recovery. Physical
power-loss, restored-backup and production shared-service readiness remain unproven.

## Layout and license

`cmd/memotrace` owns CLI/TLS lifecycle. `internal/protocol` owns pure validation;
`httpapi` authorization/orchestration; `postgres` embedded versioned SQL/RLS/jobs;
`archive` filesystem integrity/recovery; `bootstrap` verified TLS enrollment;
`contract` generated canonical snapshot and conformance helpers. `scripts` owns
component checks and explicit maintenance generators. Earlier reserved `src/`,
`tests/`, `migrations/` directories are retained; real Go tests are colocated and SQL
is embedded. Broader pipelines remain proposed in [design](docs/design.md).

Original material is **AGPL-3.0-only**. The complete [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md) accompany standalone/container builds.

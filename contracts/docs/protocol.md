# Ingestion protocol 0.1.0 — normative development contract

**Unreleased.** MUST/SHALL requirements in this document supplement
`openapi/ingestion.json` and `schemas/ingestion.schema.json`. Passing schema tests
does not demonstrate a server implements the lifecycle or storage guarantees.
JSON Schema 2020-12 definitions are selected by `$defs` name; the schema root is
a definition library, not a union that identifies arbitrary message types.

## Transport and shared representations

Deployed servers use HTTPS only, TLS >=1.2. The public ingestion routes are
`/v1/...`; unauthenticated `GET /healthz` is process liveness. JSON requests and
responses use `application/json` and UTF-8. Image bodies use `image/jpeg`.
All responses, including errors and original bytes, carry `Cache-Control:
no-store` and `X-Content-Type-Options: nosniff`. The body byte limits apply to
received bytes, not character count or an untrusted Content-Length declaration.

| Representation | Requirement |
| --- | --- |
| UUID | 36-character canonical lower-case hyphenated hex; no UUID version/variant restriction |
| SHA-256 | Digest of exact bytes, 64 lower-case hex characters |
| Credential | 32 cryptographically random bytes, base64url without padding, 43 characters; final character has zero padding bits |
| String length | Unicode scalar values, not UTF-8 bytes or grapheme clusters; user text excludes U+0000 |
| Milliseconds | JSON integer in 0..9007199254740991 inclusive |
| Byte length | JSON integer in 1..16777216 inclusive |
| RFC3339 UTC | Calendar/time-valid date-time with upper-case `T` and terminal `Z`, optional fractional seconds; offsets, missing zones, or whitespace rejected |

Runtime date-time format validation is REQUIRED; `format` as annotation alone
is insufficient. Emit ordinary RFC3339 UTC instants (seconds 00..59); the pinned
format checker does not support leap-second notation. Protocol times are not
local time. JSON numbers MUST be interpreted exactly before integer/range checks.
JSON Schema's integer semantics accept genuinely integral decimal or exponent
forms (`1.0`, `1e3`, `100e-2`); producers should emit integer decimal notation for
integer fields. Fractional `9007199254740991.1`, `1.00000000000000001`, or `1e-400`
MUST NOT become valid integers through binary-float rounding or underflow. The
fixture parser uses exact decimal parsing, converts only genuinely integral
decimals to integers, and leaves other decimals numeric for the genuine validator.
NaN, Infinity, duplicate object properties (including escape-equivalent names),
and trailing JSON data are invalid.

### Lossless UTF-8 JSON text

Wire JSON MUST be valid UTF-8 and its decoded strings, **including property
names**, MUST consist of Unicode scalar values. Reject unpaired high/low surrogate
escapes, reversed/separated pairs, and invalid UTF-8 before any decoder or storage
operation that could replace them with U+FFFD. A lossless decoder may preserve
invalid surrogates temporarily solely to reject them before further processing.
Do not repair malformed input or silently replace, strip, or normalize characters.

`device_name`, `profile.id`, and non-null `capture_settings` additionally exclude
**U+0000 (NUL)**. Their schema patterns enforce that text domain; they do not ban
other scalar control characters permitted as JSON escapes. Validate these fields
before database writes: NUL or malformed scalar text is **400 invalid_request**,
not a database-derived **503 unavailable**. This is a clarification of the
unreleased 0.1.0 contract; there are no previously released clients to migrate.

A valid JSON surrogate pair, such as `\ud83d\udcf7`, represents the same single
scalar as literal `📷` and MUST be accepted and preserved. Genuine U+FFFD (`�` or
`\ufffd`) is valid data and MUST be retained exactly; its presence alone is not
evidence of malformed input. Scalar values outside the BMP count as one character.
Schema engines must evaluate these patterns and lengths with Unicode scalar
semantics, not reject a valid astral character merely because a runtime represents
it internally using two UTF-16 code units. Combining sequences remain unchanged.

All declared objects are closed (`additionalProperties: false`), including nested
metadata/profile and response/error objects. Unknown fields are invalid. Required
fields cannot be null except the explicitly nullable pending receipt. Optional
metadata listed below may be absent or null with the same unknown meaning.

## Bootstrap and authorization

The operator transports an `Invitation` using a trusted out-of-band/manual/QR
channel. The exact required fields are `contract_version: "0.1.0"`, `server_url`,
`tls_certificate_sha256`, `invitation_token`, `expires_at`, `archive_id`.

`server_url` is an HTTPS **origin** beginning with exact lower-case `https://`:
upper/mixed-case `HTTPS://` or `Https://` is rejected, not silently normalized.
It contains a host and optional port, with no userinfo,
path (including trailing slash), query, or fragment. ASCII DNS names, IPv4, and
bracketed IPv6 are supported. A present port has **1..5 ASCII decimal digits** and
numeric value **1..65535**. Leading zeros are valid within five digits (`00001`,
`00443`); zero, six digits (even `000001`), signs, and fractional ports are invalid.
Verify and emit the **exact supplied origin**, retaining a valid explicit port
and its leading zeros rather than changing the string after trust verification.
Host/port validity must
also be checked by the consumer's URL parser: the schema's pattern intentionally
does not implement DNS/IP parsing or numeric port comparison. The certificate
fingerprint is SHA-256 of the DER leaf certificate. Verify the certificate,
hostname and validity against out-of-band trust before redemption; matching a
fingerprint does not waive name/validity checks. Pin rotation requires trusted
re-bootstrap. No insecure TLS bypass or public admin endpoint is part of this API.

Invitations are one-time, expiring credentials. The invitation CLI accepts only
**whole-second TTL durations from 1 through 600 seconds inclusive**, including its
default. It rejects zero, negative, subsecond, fractional-second, or >600-second
durations. Exact CLI spelling remains server-owned; the duration bounds do not
add a TTL field to the public Invitation object.

Derive expiry from the current instant plus that duration, preserving fractional
time at PostgreSQL **microsecond precision**. Persist and emit the same instant
using RFC3339 UTC with fractional seconds when present: for example, issuance
at `2026-09-09T12:34:56.123456Z` with TTL 1 second yields
`2026-09-09T12:34:57.123456Z`, never `2026-09-09T12:34:57Z`. Do not round the
reported expiry down to an earlier whole second. Successful CLI output MUST be
generated while the invitation is still unexpired; arrival after expiry due to
network or out-of-band transport delay is normal and redemption then returns 401.

Expiry relative to issuance/output and token randomness cannot be proven from
a schema instance. Persist only credential hashes. Invitation consumption and device creation MUST
be atomic. `POST /v1/pairing/redeem` takes `PairRequest`:

```json
{"invitation_token":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","device_name":"Synthetic device"}
```

`device_name` is 1..80 Unicode characters. A successful **201** `PairResponse`
contains only `contract_version`, `owner_id`, `archive_id`, `device_id`, and
`device_token`. The new device token is returned once. All invalid, expired, or
consumed invitations return **401 unauthorized**, without existence disclosure,
with the required challenge:

```http
WWW-Authenticate: MemoTraceInvitation realm="memotrace-pairing"
```

`MemoTraceInvitation` is the application-specific HTTP authentication challenge
for this redemption operation. It directs clients to supply `invitation_token`
in the JSON body; it is **not bearer device authentication** and does not request
a device token in Authorization. Successful redemption still returns 201.
Malformed request structure remains `400 invalid_request`; an invalid invitation
credential must not become an existence oracle. If the successful response is
lost, a consumed invitation cannot be replayed: operator revocation/re-enrollment
is required.

Every other `/v1` call requires `Authorization: Bearer DEVICE_TOKEN`. The HTTP
authentication **scheme is case-insensitive**: `Bearer`, `bearer`, `BEARER`, and
mixed-case spellings are equivalent. The credential value remains case-sensitive.
Devices are
scoped to one archive; authorized devices in that archive can read/resume its
frames. The original registering device is retained in server-owned metadata.
Clients cannot assert owner identity. Missing/invalid/revoked bearer credentials
return **401**, with the required protected-route challenge:

```http
WWW-Authenticate: Bearer realm="memotrace"
```

OpenAPI requires the operation-appropriate challenge on every declared 401
response. Header names use HTTP's case-insensitive matching; challenge values are
emitted as shown. These challenges supplement the existing `no-store`/`nosniff`
headers and do not change other error responses. Authenticated access to unknown or out-of-scope archives, frames,
receipts, or originals returns **404**, without disclosing another owner's data.
Canonical IDs and content hashes are not authorization.

Revocation rejects newly authorized requests; upload authorization is rechecked
before commit. An already-authorized in-flight download may finish after
revocation. Local operator commands provide migration, archive creation,
invitation issuance, revocation, and serving; their UX is server-owned.

## Register immutable expected metadata

`POST /v1/archives/{archive_id}/frames` accepts a `ManifestRequest` with the sole
property `frames`: **1..100** `FrameMetadata` objects. Maximum JSON body:
**1,048,576 bytes (1 MiB)**. Duplicate frame IDs anywhere in the batch return
**400 invalid_request**, even if their metadata differs. Registration is durable,
transactional and all-or-nothing: a failed batch cannot partially register frames.

Required metadata:

| Field | Meaning |
| --- | --- |
| `frame_id` | Immutable frame UUID within the authorized archive |
| `request_wall_ms` | Approximate capture request Unix wall-clock milliseconds, not shutter time |
| `sha256` | SHA-256 of the exact expected JPEG bytes, including EXIF |
| `byte_length` | Expected exact original byte count |

Optional nullable metadata:

| Field | Meaning/limit |
| --- | --- |
| `session_id` | Capture session UUID, unknown when absent/null |
| `request_elapsed_ms` | Elapsed milliseconds in the documented session/boot scope |
| `saved_wall_ms` | Unix wall-clock milliseconds of save completion; may refer to recovery |
| `capture_settings` | Opaque string, at most 2048 Unicode characters; empty string is known empty, not null |
| `profile` | Closed object described below |

A non-null profile requires `id` (string 1..64), `requested_width` and
`requested_height` (integers 1..16384), `jpeg_quality` (integer 1..100). Optional
nullable `negotiated_width` and `negotiated_height` are integers 1..16384 when
known. Requested or negotiated dimensions do not prove actual saved dimensions.
The 40-million-pixel limit applies to the actual JPEG header, not to a requested
profile's dimension product.

Normalize absent/null values for all optional metadata, including nested
negotiated dimensions, before immutable comparison. Missing/null whole profile
means unknown; a non-null profile with unknown negotiated fields is still a known
requested profile. JSON member ordering is immaterial; do not trim or reinterpret
strings. Matching normalized metadata repeats safely. Any immutable difference
returns **409 conflict**; original bytes or metadata must never be overwritten
under that identity. Same bytes under different frame IDs are separate evidence
records; this slice has no physical or cross-owner deduplication.

Do not manufacture missing legacy metadata. Wall clocks can jump. Elapsed time
is only comparable in its documented session/boot context: a nullable session
does not establish a timeline across unrelated recordings or devices. No
cross-field chronological ordering constraint is imposed on request/save times.

The **200** `ManifestResponse` has `contract_version: "0.1.0"` and `frames` in
the exact input order, one result per input. Each result has `frame_id`, `state`
(`pending` or `committed`), and `receipt`. The receipt is null **iff pending**;
otherwise it is a valid `Receipt` for the same frame and selected archive. Length,
hash, and identity must agree with immutable registered metadata. JSON Schema
enforces state/null coupling; equality/order across messages is normative runtime
work. Historical committed receipts can be returned without asserting current
original availability.

## Publish or retrieve the original

`PUT /v1/archives/{archive_id}/frames/{frame_id}/original` takes the full JPEG,
maximum **16,777,216 bytes**. Metadata registration must precede publication;
unknown frames return 404. No byte-range resume endpoint is defined. Stream,
bound, and verify the submitted bytes **even for an already committed repeat**:
different bytes must never silently succeed. Registered length/hash mismatch is
**422 checksum_mismatch**; JPEG/header/dimension failure is **422 invalid_image**.

Before a successful receipt, verify:

1. Exact byte length and SHA-256 against the registration.
2. JPEG SOI and EOI markers and a parsable JPEG header (Go `DecodeConfig`-equivalent
   header interpretation, not a requirement to use Go).
3. Actual width/height each 1..16384 and their product **<=40,000,000**.
4. Durable original publication and a durable metadata/initial-job commit under
   the server's explicitly documented local Linux filesystem/PostgreSQL settings.

The server must preserve exact original bytes, including EXIF, without re-encoding
or stripping metadata. Header checks are not full JPEG decoding, visual quality,
OCR, or ML completion. A persistent initial processing job is pending; no
processing completion may be fabricated.

The success result is **200 Receipt**, including safe repeats. Register-before-
publication permits restart recovery to roll forward a valid published original
when final SQL commit failed. Failures/disconnected responses cannot authorize
client deletion or pretend commitment. Server fault tests must exercise staging,
publication/fsync, SQL, restart, and concurrent-repeat outcomes.

`GET .../receipt` returns the stable **200 Receipt** for a committed frame;
registered pending is **409 not_committed**. Unknown/out-of-scope is 404. This is
historical lookup and can return the receipt if bytes were later damaged.

`GET .../original` returns **200** exact JPEG bytes, `Content-Type: image/jpeg`,
and `Content-Length` equal to byte count. Pending is **409 not_committed**.
Missing/corrupt committed bytes MUST be detected **before serving content** and
return **409 integrity_error**. Verify integrity before read success; neither
the receipt nor a metadata lookup proves current availability.

## Receipt meaning and stability

The exact `Receipt` object requires:

- `contract_version: "0.1.0"`, `archive_id`, `frame_id`, `sha256`, `byte_length`;
- persisted `committed_at` (RFC3339 UTC `Z`);
- `integrity: "sha256-byte-length-jpeg-header"`;
- `state: "archive_committed"`.

Receipt fields **and serialized receipt bytes** are stable across repeated PUTs
and receipt lookups. Persist the commit time; never regenerate it on retry.
An embedded manifest receipt represents the same values. A receipt records a
historical durable commit under declared storage assumptions, not perpetual
availability, indexing, backup, or successful processing. Initial archive
commit must not wait for model success. No phone eviction is implemented; an
explicit retention choice and separate implementation/evidence are required.

## Error mapping and retry

The exact shape is `{"error":{"code":CODE,"message":STRING,"retryable":BOOLEAN}}`.
Messages must be generic and must not echo SQL, filesystem paths, payloads,
credentials, or identities outside scope. The schema enforces the code/retryable
relationship, but cannot determine whether a free-text message leaks data.

| Code | HTTP | retryable |
| --- | --- | --- |
| `invalid_request` | 400 | false |
| `unauthorized` | 401 | false |
| `not_found` | 404 | false |
| `conflict` | 409 | false |
| `not_committed` | 409 | true |
| `integrity_error` | 409 | false |
| `checksum_mismatch` | 422 | true |
| `invalid_image` | 422 | false |
| `payload_too_large` | 413 | false |
| `unsupported_media_type` | 415 | false |
| `unavailable` | 503 | true |

Unknown routes return 404 (`not_found` or structured `invalid_request`, false).
Wrong methods may return structured **405 invalid_request**, false. These are
the only additional status mappings for `invalid_request`.
`x-error-statuses` and response `x-error-codes` in OpenAPI are normative mapping
annotations, checked against the schema's error enum by the quality suite.

`retryable` permits a bounded recovery strategy, not an endless loop. Correct
the intended bytes before retrying deterministic checksum errors. Use bounded
backoff for temporary unavailability or pending commit. A disconnected response
is uncertain: retrieve a receipt or repeat normalized registration/full upload.
After an explicit integrity failure, operator investigation/recovery is required;
do not relabel a historical receipt as current verified availability.

## Normative scenarios beyond JSON Schema

Consumer integration tests must use synthetic inputs and actual wire behavior:

| Scenario | Required outcome |
| --- | --- |
| Invalid/expired/consumed invitation | 401 with identical non-disclosing category and MemoTraceInvitation challenge; no extra device |
| Invitation TTL boundaries | CLI accepts 1 and 600 whole seconds; rejects 0, negatives, 0.5, 1.5, and 601 seconds |
| Fractional issuance and expiry | Persist/emit matching microsecond expiry, no downround to whole seconds; success output generated before expiry |
| HTTPS origin boundaries | Reject uppercase scheme; allow 1/65535 and leading-zero ports <=5 digits; reject 0/65536/>5 digits; preserve verified origin exactly |
| Concurrent redemption | At most one successful device issuance |
| Other owner's archive/receipt/original | 404 with valid own credential; no data/metadata leak |
| Revoked or missing credential | 401 with Bearer challenge; upload rechecks before commit |
| Bearer scheme casing | Equivalent authorization for Bearer/bearer/BEARER with the same case-sensitive token |
| Fractional numbers near integer or underflow boundaries | 400 invalid_request; no binary-float rounding into an accepted integer |
| NUL in user text or malformed UTF-8/scalars, including property names | 400 invalid_request before invalid text reaches storage; no U+FFFD repair or database-derived 503 |
| Escaped surrogate pair, literal astral text, genuine U+FFFD | Accept/preserve the same scalar sequence and bytes after UTF-8 encoding; no normalization |
| Batch contains duplicate IDs or one invalid record | 400; no partial registration |
| Legacy absent versus null optionals | Same normalized metadata, safe repeat |
| Immutable metadata differs | 409 conflict; prior evidence unchanged |
| Same bytes under two IDs | Two distinct evidence records |
| Pending receipt or pending original | 409 not_committed with retryable true |
| Truncated/wrong-length/hash original | 422 checksum_mismatch; no successful receipt for bad bytes |
| Matched bytes with malformed JPEG/header or excessive dimensions/pixels | 422 invalid_image; no successful receipt |
| Manifest >1 MiB or upload >16 MiB | 413 payload_too_large even if declared Content-Length lies |
| Lost upload ACK, concurrent/full repeat, restart | Same receipt and exact original, one initial processing job |
| Valid original published before final SQL failure | Preserve pending metadata; idempotently recover/roll forward |
| Publication/fsync/SQL/resource failure | No invented receipt; resolve uncertainty through authorized retry/recovery |
| Later committed-original corruption/missing file | Historical receipt may remain; original read refuses with 409 integrity_error |
| Error/privacy checks | Generic messages and no sensitive payload/token/path logging |

Tests here exercise the expressible schema limits and explicitly demonstrate
some schema-valid semantic counterexamples (duplicate IDs, mismatched receipt
identity, expired invitation). They do not implement a pretend server or claim
these runtime scenarios passed.

## At-rest and deployment assumptions

The alpha trusts the local operator and relies on operator-provisioned encrypted
volumes and backups. The application does not implement E2EE or attest encryption,
and does not promise admin-root-proof protection. Operators must back up/recover
keys and certificates alongside encrypted storage/backups; credential reset
alone does not recover lost encryption keys. Default listen is loopback with
explicit LAN bind; no global plaintext deployment flag. Secrets/DSNs are external
configuration, never committed or logged. Two-owner isolation tests do not by
themselves establish readiness as a production shared service.

See [release/compatibility policy](releases.md) before changing any wire or semantic
requirement, and [quality gates](quality.md) for the limits of contract evidence.

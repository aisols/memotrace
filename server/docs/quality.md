# Verification and contract provenance

## Required command

From the component root: **`bash scripts/verify.sh`**. Linux, Go 1.26.4, Python 3,
Docker are required. The command checks exact Go version, gofmt, module checksums,
vet, binary build and canonical snapshot hashes/definitions, then provisions its own
uniquely named PostgreSQL-15 container with random password, ephemeral loopback port,
ownership label and EXIT/INT/TERM cleanup. It never reuses an operator database.

It runs `go test -race -p 1 -count=1 -timeout=5m -coverprofile=.build/coverage.out ./...`
with PostgreSQL **required**; missing DSNs/service fail, never silently skip. Packages
serialize because an integration test installs a deferred SQL-failure trigger;
explicit concurrent handler tests still exercise parallel requests. It then enforces
the component-local pure/domain coverage gate. Artifacts live in ignored `.build/`.
`go test ./...` alone explicitly skips unavailable DB tests and is not the full gate.

## Behavioral tests

- `TestCLICompleteTLSLifecycleAndShutdown`: actual CLI subprocesses for repeat
  migration, archive creation, TLS serve, verified invitation, pairing, upload/read,
  revocation and signal shutdown/lock release. Its `canonical_invitation_origin_and_TTL`
  subtest checks lower-case raw HTTPS origins, port length/range, rejection without
  insertion, and a future 1s invitation whose emitted expiry exactly matches PostgreSQL.
- `TestInvitationTTLValidatedBeforeDatabaseAccess` and
  `TestInvitationExpiryPreservesSubsecondTimeAtMicrosecondPrecision`: reject fractional/
  out-of-range TTLs before database use and retain fractional UTC time deterministically.
- `TestPairingSingleUseExpiredConcurrentAndRevoked`: invalid/expired/consumed tokens,
  concurrent redemption and revocation.
- `TestTwoOwnersExactBytesStableLostACKAndSameArchiveResume`: owner isolation on
  manifest/original/receipt, registering-device preservation, exact EXIF-like bytes,
  pending state, stable ACK bytes, one pending job, later corruption/missing file
  with historical receipt availability.
- `TestManifestAtomicityLegacyNormalizationAndStrictBounds`: conflict rollback,
  duplicate IDs, legacy/profile null normalization, schema-invalid field corpus,
  actual handler limits and mathematical integer JSON.
- `TestUploadMalformedOversizedAndConcurrency`: body/media limits, malformed JPEG,
  submitted-byte conflicts even on committed retries, concurrent stable receipts/jobs.
- `TestHTTPJPEGHeaderDimensionAndPixelBoundaries`: 16384×1, 1×16384 and 8000×5000
  headers accepted; 16385 dimensions and >40,000,000 pixels rejected with `invalid_image`.
  Synthetic SOF changes exercise header-only validation, not full large-image decoding.
- `TestHTTPExactly16MiBJPEGIsAcceptedAndRetryStillChecksBytes`: a complete valid JPEG
  padded with legitimate COM segments to exactly 16 MiB is committed/read/repeated
  byte-for-byte; a same-length conflicting retry fails with `checksum_mismatch`.
- `TestHTTPUnicodeScalarsRejectWithoutRowsAndPreserveImmutableText`: reject unpaired
  high/low surrogate escapes before Go can replace them, including keys and escaped-
  backslash cases; retain U+FFFD, paired/raw astral characters and decomposed scalar
  sequences without normalizing text or overwriting it on a conflicting repeat.
- `TestHTTPNULAndSurrogatePairingDoNotConsumeInvitation` and
  `TestHTTPNULBatchRegistrationIsAtomic`: invalid text yields `invalid_request`, no
  device/consumed invitation or partial frame batch; valid text persists exactly.
- `TestHTTPAuthSchemeCaseTokenExactnessAndChallenges` and
  `TestHTTPInvitationUnauthorizedChallenge`: case-insensitive scheme with RFC 6750
  one-or-more ASCII-space separation, exact token, duplicate-header rejection,
  missing/invalid/revoked credentials and correct challenges. Two/eight-space cases
  retrieve the same historical receipt; another owner's credential remains 404,
  revoked credentials remain 401. Tab/missing separators, trailing token whitespace
  and malformed credentials stay rejected.
- `TestOpenAPIRequiredChallengeHeadersAreActuallyChecked`: the conformance helper
  fails both missing required challenge headers and incorrect canonical constants.
- `TestRevokedWhileStreamingCannotCommit`: revocation during body streaming prevents
  publication/commit.
- `TestPendingPublishedFaultsRecoverAndDoNotLeak`: simulated ENOSPC, file fsync,
  publication, directory fsync, SQL-boundary faults; no premature ACK, restart recovery,
  generic errors without sensitive internals.
- `TestActualSQLCommitFailureRollsForward`: a deferred PostgreSQL trigger fails the
  **actual COMMIT**, then recovery commits one job.
- `TestProcessCrashAfterPublicationBeforeCommit`: subprocess exits without cleanup
  after durable publication; lock releases and restart validates/rolls forward.
- `TestRLSMissingContextPoolReuseAndUnsafeRuntimeRole`: unscoped and cross-owner
  denial on reused runtime connections, private auth-table and immutable-update
  denial, privileged-runtime rejection.
- Archive unit tests: no-clobber, exclusive/private root, symlink defense, streaming
  bounds, failure boundaries and preservation/reporting of unknown/staged files.
- `TestTrustedTLSBootstrapPinOriginNameAndValidity`: synthetic certificate name,
  validity, origin, pin and live-leaf changes; ordinary TLS verification stays enabled.
- Pure domain tests cover metadata/profile/string/time bounds, exact JSON/credential
  syntax and normalization, JPEG dimensions/pixels, length/hash/header checks and
  error retry mapping.

All JPEGs, EXIF-like bytes, certificates, credentials and identities are synthesized
at runtime. No private archive, device, cloud service or committed key is required.
These are process/fault-injection checks, not physical power-loss/device evidence.
Shared HTTP test assertions compare every returned receipt field against registered
archive/frame/hash/byte length and persisted commit time, including embedded manifest
and concurrent-upload receipts. Registration checks also compare full persisted
metadata to the test's input. Error checks assert exact expected `error.code` and
retryability; ambiguous 409/422 statuses require an explicit expected code.

## Pure/domain coverage gate

Require **>=85% statement coverage of `internal/protocol`**, separately from HTTP,
CLI, SQL and filesystem orchestration. This deterministic package decides immutable
metadata validity/normalization, exact JSON/credential syntax, pre-receipt content
limits and retry policy. Small decision surfaces have high evidence-integrity impact;
test valid boundaries and adversarial alternatives. Residual defensive reader/seek
branches do not justify an arbitrary whole-application percentage. The runnable
`scripts/coverage.py` enforces this independently approved 85% gate, preserved through
the review fixes. Never lower it to pass. Behavioral DB/fault tests remain
mandatory regardless of percentages. Go's package-local report can show 0% for
database code exercised by another package's integration tests.

**Independent verification completed on 2026-09-09:** main reran the full server
command on the latest implementation, including the RFC 6750 separator fix, and
both independent reviewers reported PASS after all eight findings were resolved.
See the [dated verification record](verification-2026-09-09.md) for main-supplied
commands/results, contract isolation checks, snapshot hashes, container evidence
and limits. Main's pure/domain result is **95.2% (238 covered statements / 250 total)**,
matching the earlier builder result; the independently approved 85% gate remains.
This evidence identifies the uncommitted, unreleased working tree based on `f4e53f8`,
not an invented implementation commit or hosted CI run. Verification provisions a non-superuser local admin that
owns its dedicated database/schema and a separate nonowner runtime role, exercising
the documented ownership setup rather than depending on superuser migrations.

Final scope follow-up: the independent RFC 6750 §2.1 finding changes only consumption
of the ASCII-space separator after the scheme. It does not trim token suffixes or
relax credential validation, owner scope, revocation or duplicate-header handling.
The canonical schema and version are unchanged. Builder and subsequent independent
main runs of `bash scripts/verify.sh` passed after this separator fix, including
race-enabled PostgreSQL/CLI/conformance tests, vet, formatting, module checks and build.

## Controlled canonical snapshot

`internal/contract/snapshot/manifest.json` pins **contract 0.1.0**, source component
`contracts`, source base revision **`f4e53f8`**, and explicit **`unreleased-working-tree`**
provenance. It does not claim working-tree bytes are already committed/released.
Three SHA-256 entries identify the exact canonical schema, OpenAPI and `VERSION`
bytes. Embedded checks require `VERSION` to match the provenance manifest and
`protocol.Version`; maintenance refresh also checks schema/OpenAPI version agreement.
Builds/tests use only
the consumer-local embedded snapshot, never sibling checkout content.

The pinned genuine JSON Schema 2020-12 validator `jsonschema/v6` v6.0.2 asserts formats
and uses local resources. Its supported `regexp2` v1.11.0 ECMAScript/Unicode engine
handles canonical `\u` regex escapes without altering schema bytes. Actual handler
responses and CLI invitation are schema validated. OpenAPI checks compare actual
operation/status/media/schema/error code and validate every defined present/required
response header against its canonical schema, including challenge constants. Decoded
valid/invalid request corpora are independently schema checked then sent through
actual handlers/PostgreSQL. Raw malformed Unicode escape cases have explicit wire
regressions because a lossy JSON decoder can erase that invalid syntax before schema
validation sees the instance. Additional assertions cover facts not
expressible in schema: identity/byte equality, scope, stable ACK, duplicate IDs,
transactions, fsync ordering, concurrency and recovery. Production does not import
the test-only validator or fetch schema URLs.

Refresh only as an explicit reviewed maintenance action:

```sh
python3 scripts/refresh-contract.py --source /path/to/canonical/contracts \
  --source-base f4e53f8 --provenance unreleased-working-tree
```

The generator copies canonical bytes and deterministically records hashes/version.
Add `--check` to verify parity with an explicitly selected canonical source without
changing the snapshot. This source comparison is a maintenance/coordination command,
not an ordinary sibling build dependency.
After release use its actual reviewed revision and `released-revision`; review diffs
and rerun all checks. Outer assembly owns cross-component coordination.

`go.mod`/`go.sum` pin dependencies. Dockerfile build/runtime images are digest-pinned;
the PostgreSQL-15 test digest was actually inspected locally. Run
`python3 scripts/dependency-notices.py` to regenerate selected build/test license
texts. The maintenance-only `--project-license /explicit/path/LICENSE` refreshes the
full AGPL copy without introducing a parent build dependency. Standalone/container
distributions include the full license and notices.

## Remaining gates

Independent main verification and both reviews are complete for the working tree
recorded above. Hosted CI has not run: no push/PR was requested. Before merge, satisfy
the required PR/CI gates and verify the latest applicable revision. Subsequent source
changes require applicable checks/review to be rerun; this dated evidence does not
automatically cover them. Container and isolated-component evidence retains the
specific scope and limitations in the dated record.
No physical power-loss, encrypted-volume attestation, restored-backup, Android sync,
device, throughput/large-root benchmark or production shared-service evidence exists.

# Verification and contract provenance

Current retrieval extension: the required Go verifier enforces independently
approved **>=85% statement coverage for each of `internal/protocol` and
`internal/retrieval`**, independently rather than averaging the packages. New lifecycle,
populated-v1 migration, lease/retry/fencing/COMMIT-failure, owner isolation, scope,
exact cutoff/history/source exclusion and actual CLI/TLS tests run in that same
disposable-PG/race gate. The independently built ML component has its own
[Python checks](../ml/README.md); those are separate from Go/model-free verification.
See [retrieval commands](retrieval.md) and the
[current source-local evidence](../benchmarks/object-search-experiment-2026-09-14.md).
The report binds actual uncommitted experiment source hashes over `39b24e3`, records
passing local component/Docker/parity gates, and documents a passing 100-image
genuine-model Go CLI/TLS smoke, 7/7 response schemas and independent exact-query
matching. The new object-search gate passed 226 tests and **612/636 = 96.23%** pure-
core statements against its independently approved **>=95%** gate; **186/210 branches**
are reported separately. ML's independently approved images statement gate remains
**>=95%**. Server-source extraction passed with provisioned dependencies; hosted CI,
delivery/deployment, official VQ2D and production gates remain pending. Private
provenance and the narrow PTS scan's limitations are recorded with the evidence. The
[2026-09-13 record](../benchmarks/everyday-object-evaluation-2026-09-13.md) and
[dated main verification](retrieval-main-verification-2026-09-10.md)
retain their historical scope; the latter's CLI/TLS and benchmark evidence is
pre-hardening. The
[review-fix builder record](retrieval-review-verification-2026-09-09.md) and ingestion
record below are also retained as historical evidence.

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

## External retrieval evaluator gate

The generic blind/staged [retrieval evaluator](retrieval-evaluation.md) is offline
diagnostic tooling in `scripts/`, outside packaged ML and the Go-only image. From
`server/`, run:

```sh
uv run --locked --project ml python scripts/verify_retrieval_eval.py
```

The verifier uses the dependencies already pinned by `ml/uv.lock`. It runs Ruff
check/format, strict mypy, and inline neutral synthetic pytest cases under branch
coverage. Coverage data/JSON use a unique private temporary directory that is cleaned on
success or failure; the verifier runtime-validates exact source membership and exact
non-bool nonnegative counters after rereading JSON. It fails on malformed coverage,
missing files, or empty test discovery. The independently enforced gate is **100%
reachable statement coverage for each of `scripts/retrieval_eval_core.py` and
`scripts/retrieval_eval_metrics.py`**; neither file can offset the other. Branch coverage
is reported separately without a threshold. This gate downloads no model or data and
does not establish media PTS, tracking, licensed-data access, official dataset metrics,
or production behavior. The evaluator's documented practical caps bound vectors,
galleries, candidates, annotations, and metric outputs before materialization. Full and
overlap phases also cap exact requested scalar vector elements before any dot product;
shared galleries are finite-validated once per collection rather than once per query.
Post-ranking capture/distance uses a deterministic linear sweep bounded by accepted
aggregate candidates plus intervals, not their Cartesian product. These are complexity
bounds and validation semantics, not measured runtime speedup claims. Sensitive
evaluator, annotation, and result dataclasses use redacted default representations.

## Object-search experiment gate

The separate [offline experiment](object-search-experiment.md) has an executable
component-local gate, also wired into ingestion CI. From `server/`, run:

```sh
uv run --locked --project ml python scripts/verify_object_search.py
```

It uses the existing locked ML dependencies, Ruff lint/format, strict mypy and
synthetic core/vision/runner tests without pretrained weights or data acquisition.
The independently approved **>=95% statement gate applies only to
`scripts/object_search_core.py`**. Its deterministic shortlist, exclusion, geometry,
association and coverage rules need direct boundary/adversarial checks because
errors can misrepresent evidence. Branch coverage is reported without a threshold;
neither branches nor other modules can offset missing core statements. The verifier
rejects missing/empty/malformed coverage and checks the exact file membership.
This experiment remains outside the production ML fingerprint and Go-only image;
real-model quality and private timing/association evidence are separate checks.

## Pure/domain coverage gates

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

The independent Go review additionally approved **>=85% statement coverage of
`internal/retrieval`** for this first implementation. Its pure rules decide exact
query/geometry acceptance, worker-result identity/norm validity, candidate exclusion,
deterministic ranking, selected clocks, complete temporal bounds and truncation.
Errors in these decisions can create misleading evidence even when IO succeeds;
valid endpoints, adversarial alternatives, tiny adjacent decimals and incomplete
coverage therefore need explicit behavioral regressions. `scripts/coverage.py`
enforces both package gates and fails if either package's coverage is missing.
This is not an arbitrary whole-server percentage and cannot be offset by coverage
in CLI/HTTP/SQL orchestration. The newly approved gate does not lower the legacy one.

Additional opt-in, model-free Go/real-Python decode IPC regression (requires the
installed locked ML virtual environment, downloads no model/data):

```sh
MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python" bash scripts/verify.sh
```

`TestHTTPPythonDecodeFailureAndExactQueryPixels` ingests a header-valid JPEG with
broken entropy and proves the genuine Python decoder fails before test-encoder
inference, yielding generic503. Unsupported text remains400. It also checks exact
subnormal/adjacent-decimal query endpoints through HTTP/Go/JSONL/Python rasterization
to one touched pixel column. Ordinary Go verification does not require an installed
ML runtime; its subprocess IPC tests independently enforce operation-aware errors
and lossless decimal forwarding. New CLI subprocess regressions hold stdin open,
send SIGTERM, and prove prompt exit/root reacquisition; input has its own30s deadline
and is validated before database/root locking.

**Historical ingestion verification on 2026-09-09:** main reran the full server
command on that ingestion revision, including the RFC 6750 separator fix, and
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

`internal/contract/snapshot/manifest.json` pins **bundle 0.2.0**, source component
`contracts`, source revision
**`5f5ac49e03b25f805f5a89f791727d0c3bd18642`**, and explicit
**`unreleased-revision`** provenance. That commit contains the exact canonical bytes,
but bundle 0.2.0 has not been released.
Five SHA-256 entries identify the exact ingestion/retrieval schema and OpenAPI pairs
plus `VERSION`. The manifest's `contract_version` is the bundle version;
`wire_versions:{ingestion:"0.1.0",retrieval:"0.2.0"}` distinguishes wire families.
Embedded checks require `VERSION` to match the bundle manifest, and each wire
family to match its separate Go constant. The maintenance refresh checks each
schema/OpenAPI pair's version. `protocol.Version` stays 0.1.0 for Android ingestion.
Builds/tests use only
the consumer-local embedded snapshot, never sibling checkout content.

The pinned genuine JSON Schema 2020-12 validator `jsonschema/v6` v6.0.2 asserts formats
and uses local resources. Its supported `regexp2` v1.11.0 ECMAScript/Unicode engine
handles canonical `\u` regex escapes without altering schema bytes. Actual handler
responses and CLI invitation are schema validated. OpenAPI checks compare actual
operation/status/media/schema/error code and validate every defined present/required
response header against its canonical schema, including challenge constants. The
conformance-only semantic oracle also verifies coverage partitions/truncation,
original-path identity, positive-area geometry, selected-clock membership, evidence
bounds/chronological order and exact untruncated group/history bounds. Truncated
history may retain temporal first/last while selecting only unsequenced evidence.
When the actual request is supplied, it additionally checks generation, result
budget, threshold, source exclusion, exclusive cutoff and gap consistency. These
instance-local checks complement DB tests; they cannot prove omitted corpus truth.
Decoded
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
  --source-base 5f5ac49e03b25f805f5a89f791727d0c3bd18642 --provenance unreleased-revision
```

The generator copies canonical bytes and deterministically records hashes/version.
Add `--check` to verify parity with an explicitly selected canonical source without
changing the snapshot. This source comparison is a maintenance/coordination command,
not an ordinary sibling build dependency.
For uncommitted bytes use their base revision and `unreleased-working-tree`. After
an actual release use its reviewed revision and `released-revision`; review diffs
and rerun all checks. Outer assembly owns cross-component coordination.

`go.mod`/`go.sum` pin dependencies. Dockerfile build/runtime images are digest-pinned;
the PostgreSQL-15 test digest was actually inspected locally. Run
`python3 scripts/dependency-notices.py` to regenerate selected build/test license
texts. The maintenance-only `--project-license /explicit/path/LICENSE` refreshes the
full AGPL copy without introducing a parent build dependency. Standalone/container
distributions include the full license and notices.

## Remaining gates

The [2026-09-14 evidence record](../benchmarks/object-search-experiment-2026-09-14.md)
documents local component, Docker, parity, genuine-model Go/PostgreSQL CLI/TLS and
public/private diagnostic results plus independent review. Its source inventory
identifies uncommitted work, not a released artifact. Server-source extraction is
complete: a server-only snapshot of cached/tracked plus intended untracked files
passed the isolated 226-test object-search verifier (Ruff, strict mypy, 96.23% core
statements), 231-test ML verifier and full Go PostgreSQL/race/decoder gate (protocol
94.4%, retrieval 95.2%). Imported ML and all three object-search modules resolved
inside the snapshot. The existing locked-dependency interpreter used `PYTHONPATH`
set to the isolated ML/server roots; this was not a fresh venv or offline bootstrap.
The [2026-09-13 record](../benchmarks/everyday-object-evaluation-2026-09-13.md) and
dated full verification in the
[main record](retrieval-main-verification-2026-09-10.md) retain their historical
scope; the latter is pre-hardening evidence. The snapshot pins canonical contract commit
`5f5ac49e03b25f805f5a89f791727d0c3bd18642`, which contains the exact bytes but
is unreleased. No hosted result is claimed. Required delivery/CI gates remain;
later source changes require
applicable verification rather than inheriting this evidence. Isolated execution
used provisioned locked dependencies, not a fresh offline installation. The Go-only
container and native-host ML runs establish different runtime boundaries.
No official VQ2D, physical power-loss, encrypted-volume attestation,
restored-backup, Android sync/device, throughput/large-root,
deployment or production shared-service evidence exists. Authorized/licensed private
input use and the narrow source-clip PTS check remain distinct from missing canonical
content/frame-zero, whole-cohort timing and reproducible acquisition provenance.

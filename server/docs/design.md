# Server Foundation Design

Status: The broader foundation remains proposed under
[ADR 0005](../../docs/decisions/0005-server-foundation.md). An **unreleased first
ingestion slice** now implements Go 1.26.4, PostgreSQL 15, TLS pairing/auth,
contract 0.1.0 manifests/originals/receipts, RLS, filesystem recovery and initial
pending jobs. See the executable [README](../README.md), [storage boundary](storage.md)
and [quality gates](quality.md) for current behavior/evidence. Python inference,
models, retrieval, leases and subsequent stages remain recommendations.

## Product Role and Baseline

The server is long-term memory, computation, and retrieval for a personal visual
history of at least 1–2 years, with room to extend retention. Preserve an evidence
archive first; build useful indexes and reconstruct difficult events when asked.
Daily VLM analysis of every frame is neither the product premise nor the plan.
[SPEC.md](../../SPEC.md) remains the original baseline, including its Python/FastAPI
preference; this proposal records the rationale for a different core recommendation.

The phone is the sensor/client: store originals and durable local queue state,
then synchronize. The [interaction requirements](../../docs/ux/README.md) require
automatic bulk sync on power with the home server reachable on the allowed LAN,
manual sync without external power, and no automatic upload merely on joining
home Wi-Fi. Whether unplugging pauses an active automatic transfer is open.
Foreground query-photo transfer policy must be distinguished from bulk sync.
These are capability requirements: the [baseline recorder](../../android/README.md)
is local-only and does not implement synchronization.

The reference processing host is Linux, Ryzen 9 5950X, 64 GB RAM, without GPU.
CPU embeddings/OCR are intended; no local VLM is planned for alpha. Model quality,
RAM use, disk needs, and sustainable throughput require actual measurements.
The [data-protection design](../../docs/architecture/data-protection.md) defines
trusted processing and its administrator/endpoint limits for all pipelines below.

## Archive and Indexing Pipeline

1. Authenticate the registered device and derive authorized owner/archive scope.
   Negotiate manifest/content needs using the public ingestion contract.
2. Receive bounded immutable payload bytes, verify length/checksum and required
   format checks, durably publish the original, and commit metadata plus durable
   processing work. Only then issue an archive receipt.
3. Decode under limits; assess quality/blur, near-duplicates, scene changes, and
   keyframe candidates. Preserve references to every original and selection reasons.
4. Embed important whole frames. Add selective spatial crops or object/region-of-
   interest (ROI) crops for small items, hands, documents, or new appearances.
5. Detect likely text regions, recognize text, retain raw/normalized OCR and its
   confidence/language, and aggregate complementary readings across an episode.
6. Publish versioned visual, OCR full-text, semantic-text, and temporal indexes.
   Keep processing failures and incomplete coverage visible independently of ingest.

The receipt is independent of expensive decoding/ML and backup completion; the
minimal pre-receipt format-validation depth must be explicit in the contract.
Later decode failure must not turn a committed original into an unreported loss.
Do not auto-delete originals for blur, occlusion, perceptual similarity, or model
interest. Excluding a frame from a default index is a reversible compute/retrieval
choice. Exact byte/identity retry deduplication and perceptual compute selection
serve different purposes; neither authorizes cross-owner deduplication.

## Query and Evidence Pipeline

Accept text, speech-derived text, a photo, or an explicitly selected crop as
capabilities are implemented. Combine compatible cross-modal text/image retrieval
with OCR full-text, semantic-text, and temporal constraints. Group candidates into
episodes and fetch authorized neighboring originals. Additional crops or targeted
retrospective reprocessing may improve uncertain candidates.

Return a useful local result with evidence frames, time context, index coverage,
and honest uncertainty. Optionally, with explicit cloud permission, send only a
small selected evidence set and necessary query context to a cloud VLM for
reranking or temporal reasoning. An unavailable/rejected cloud request leaves the
local result usable. Local search must work offline and with `Cloud AI = OFF`.

First/last observed means first/last supported observation in available indexed
evidence, not the object's first/last physical existence or proof of acquisition.
Separate directly visible facts from hypotheses about placing, carrying, or buying.
Scores are not calibrated probabilities by default; do not manufacture precise
certainty or hide missing footage, weak matches, clock ambiguity, or index gaps.
Every conclusion should lead back to the original evidence and nearby sequence.

Stable Object, Observation, and Event concepts remain later work. Lazy provenance
can begin with earliest confident episode clusters, examining neighboring frames
only when needed. Later sightings must not overwrite earlier provenance. Dialogue
references such as “where did it come from?” should retain an authorized evidence
reference, not invent a persistent object identity before evidence supports one.

## Technology Recommendation and Alternatives

Prefer a **Go core** for API, pairing/authentication/authorization, ingestion,
archive persistence, SQL migrations, durable jobs, retrieval, and optional reasoning
integration. Explicit types and error handling, networking libraries, and bounded
concurrency are a maintainability fit for this orchestration-heavy core. Go does
not prevent faulty authorization, ignored errors, nil misuse, races, or incorrect
durability ordering. Those need review and meaningful failure tests.

Keep **Python inference** narrow to retain direct access to model ecosystems and
reference preprocessing. Require strict Pyright or mypy checking (choose one with
implementation), typed boundaries, runtime validation, and pinned dependencies.
Dynamic typing does not prohibit static checks. OpenCV, ONNX Runtime, PyTorch and
other numeric engines execute substantial compiled native code; profile actual
decode, inference, IPC, and persistence time before blaming Python overhead.

| Alternative | Benefit | Cost and decision condition |
| --- | --- | --- |
| Full Python/FastAPI | Original SPEC preference; quickest model/API iteration, one application language | Viable with strict checks and disciplined boundaries; less preferred for the long-lived core, not inherently unreliable |
| Go plus Python inference | Explicit core and broad ML compatibility | Two runtimes, packaging, IPC validation, supervision, observability and failure propagation; preferred balance, pending review |
| Go plus ONNX native bindings | May remove production Python for compatible models | C API/community wrapper, FFI ownership and native-library deployment; export and preprocessing parity required; not automatically a pure static binary |
| Rust core/inference bindings | Stronger compile-time safe memory/concurrency guarantees | Greater implementation complexity and learning/review cost; unsafe/native ML FFI and domain/auth logic still need scrutiny |
| C#/.NET plus ONNX Runtime | Official ONNX API, strong tooling and typed service implementation | Compelling if production Python must be excluded; still validate model support, quality, preprocessing, native dependencies and operations |

No “no Python in production” requirement has been finalized. Do not downgrade a
model merely because a binding/export is convenient. Compare reference output,
tokenization, image orientation/color handling, resize/crop normalization, and
numeric precision before adopting an alternate runtime. Language choice is not
a security certification or a substitute for measuring the full pipeline.
The [official ONNX Runtime API inventory](https://onnxruntime.ai/docs/api/), accessed
2026-09-09, distinguishes official APIs from community bindings; no binding is pinned.

## Component and Process Boundaries

The core and inference process/worker pool belong to the same `server/` component
and release. They are not independently deployed microservices created to prepare
for a repository split. Keep cohesive API, ingestion, archive, jobs, processing,
search, reasoning, and storage responsibilities within that ownership.

The core supplies a job-scoped read-only input or bounded byte stream and explicit
model/settings identity. Inference has no database credentials, SQL transactions,
queue claim/retry policy, or archive-delete authority. Give it only needed data,
temporary storage, CPU/memory/time limits, and restricted egress. A process split
is useful isolation only when permissions actually enforce these limits.

Use private typed, versioned IPC owned by `server/`, distinct from public contracts.
Local stdio, Unix-domain sockets, or RPC are candidates; transport and encoding
remain open. Specify request/result correlation, length limits, cancellation,
timeouts, worker death, version mismatch, and errors when implementing the boundary.
Validate outputs before persistence: finite vectors of the expected dimension and
space, bounded text/collections, valid crop coordinates, supported versions, and
matching source identity. Malformed or stale worker output must not become evidence.

The server owns its build manifests, lockfiles, container build, migrations, and
component tests. Introduce real reproducible commands with working targets. Its
container context is `server/`; [deploy/](../../deploy/README.md) owns Compose
assembly and eventual pinned production images. The legacy reserved Python source
directory is not a commitment to a Python-only build. Public definitions come from
pinned contract artifacts or controlled version/revision/checksum snapshots, never
sibling source imports or a live server required for ordinary builds.

## Storage, Durability, and Jobs

Propose PostgreSQL plus pgvector for owner/device metadata, temporal relationships,
OCR full-text and vector indexes. Start originals on the filesystem; use SSD/NVMe
for active originals, database/indexes, thumbnails, and processing cache. Archival
HDD tiers can follow measured capacity/latency needs. Keep storage roots outside
the checkout. Stable archive identifiers resolve through server-owned storage
metadata; a client local URI is never a persistent server path.

Original payload bytes are immutable. A retry with the same identity and bytes
returns the established result; different bytes conflict rather than overwrite.
Derived data can be regenerated under versioned processing settings. Encryption
at rest must preserve the ability to recover the exact original payload identified
by the public receipt, not replace it with a re-encoded JPEG.

Filesystem publication and SQL do not share a transaction. Proposed ordering is:

1. Validate authorization and bounded upload intent; stream to private staging,
   computing length/checksum without loading the entire archive into memory.
2. Verify the payload and durably publish it without clobbering an existing original.
   Use atomic publication on the supported filesystem and fsync file/directories
   where applicable; document mount/storage assumptions and handle errors.
3. In one database transaction commit archive metadata and durable initial job
   state (or a transactional outbox equivalent). The initial queue recommendation
   is PostgreSQL itself; Redis/Kafka is not a requirement.
4. Return the durable receipt only after both original and metadata/job commit
   succeed. If the response is lost, authorized receipt lookup/retry recovers it.

| Interrupted boundary | Required recovery behavior |
| --- | --- |
| Partial staging, no published original | Never acknowledge it; resume/retry or expire only known incomplete staging |
| Published original, no metadata commit | Track/reconcile the orphan; verify and roll forward or quarantine for diagnosis without silently deleting evidence |
| Metadata and job committed, reply lost | Recover the existing receipt; do not create a second frame or uncontrolled work |
| Worker stops, lease expires | Reclaim under bounded retry policy and persist results idempotently |
| Metadata references missing/corrupt bytes | Mark an integrity incident, avoid claiming the original is available, preserve diagnosis and seek repair |
| Disk full, failed fsync or database commit | No premature durable receipt; retain recoverable state and expose a bounded actionable failure |

Atomic rename is not by itself a power-loss guarantee. Test crash boundaries on
the declared storage configuration; reconciliation must be idempotent and track
orphans/missing originals. Periodic integrity verification, recovery visibility,
and backup/restore are separate from successful initial checksums.

Jobs are **at least once**, with lease/claim/reclaim, bounded retry/backoff,
timeouts, resource caps, and quarantine for persistent failures. Do not promise
exactly-once execution. Deduplicate committed results by owner/source identity and
version plus model, preprocessing, and settings versions; prevent late results
from superseded leases or deleted sources from becoming current. The core owns
all of this, while inference computes one bounded invocation.

Maintain separate ingestion, indexing, failure/backlog, and backup status. Fairness
and query priority must prevent bulk reindexing from starving new uploads or local
search. Bound decoder/OCR/crop pools and native runtime threads together to avoid
CPU oversubscription and RAM exhaustion. Shared operation adds per-owner quotas
and fair queues rather than assuming one archive can consume the whole host.

## Search Storage and Model Provenance

Use a canonical compatible visual space for text/image queries in a given index
generation. Retain model identity/version, weight artifact digest and license,
preprocessing/tokenizer version, input resolution, precision, runtime/export
identity, settings, source version, and result creation time. Model weights remain
external artifacts with provenance, not Git content.

Equal vector dimensions do not imply compatible embedding spaces. Never silently
mix embeddings from different models, preprocessing, or precision changes assumed
equivalent without validation. Version index generations, reindex incrementally,
track coverage, and make query routing explicit while old and new generations
coexist. Retain enough configuration to reproduce results within declared numeric
tolerances; do not promise universal bit-for-bit equality across runtimes/hardware.

Benchmark pgvector and temporal filtering against the required archive horizon.
Time partitioning, index type, dimensions, and retrieval-fusion/reranking strategy
remain measurement-driven choices. Recent “where?” queries and earliest-provenance
queries have different access patterns. Scope every retrieval channel, neighbor
fetch, evidence artifact, and cache to the authorized owner.

## Capacity and Benchmark Plan

At two-second cadence for 16 hours, SPEC assumes 28,800 frames/day: 10,512,000 per
365-day year and 21,024,000 over two years, excluding bursts and missed captures.
Use decimal storage units in these arithmetic projections:

| Input assumption | Originals/day | Originals/year | Originals/two years |
| --- | --- | --- | --- |
| SPEC illustrative 300,000 bytes/JPEG | 8.64 GB | 3.15 TB | 6.31 TB |
| Historical observed mean 2,821,452 bytes/JPEG | 81.26 GB | 29.66 TB | 59.32 TB |

The second row comes from the [2026-09-09 Android verification](../../android/docs/verification-2026-09-09.md#archive-and-pause):
660 stored entries, old quality-95 profile, with three sampled 4000x3000 JPEGs
decoded/checked. It is a scoped observation from a private scene, not a general
capacity benchmark. These projections exclude backups, derivatives, indexes,
bursts, replication, and filesystem overhead. The SPEC shorthand of about 8.6 GB/day
and 3.1 TB/year was an assumption. Neither row predicts `1440x1080 Q90` or the
other current profiles. The [dated A33 profile evidence](../../android/docs/profiles-verification-2026-09-09.md)
records one native sample per profile across all six profiles and 18 normal
captures. These bounded observations are not a controlled benchmark, a battery
or capacity guarantee, or verification of the final merged revision.

Processing 28,800 incoming frames within eight hours means averaging one incoming
frame per second across the overall pipeline; two to four hours means two to four
frames per second. This does not require every inference stage on every raw frame.
Measure selection ratio and recall loss as well as processing speed; keyframe
pruning must not hide missed short actions or small/occluded objects.

Following the [benchmark policy](../benchmarks/README.md), record reproducible
dataset/query/expected-episode identities, redistribution rights, host configuration,
model/runtime provenance, and both cold/warm behavior. Evaluate:

- Russian text-to-image retrieval, the yellow screwdriver scenario, photo/crop
  queries, small-object visibility, document OCR, and earliest-context provenance.
- Episode Recall@5/20/100. SPEC's Recall@20 >=90% target for well-visible objects
  is a goal, not a result; report small/occluded objects separately. Distinguish
  capture-event coverage (SPEC target >=95%) from indexing and retrieval failures.
- Decode, preprocessing, embedding, crop and OCR latency/throughput; IPC/DB costs;
  CPU, memory, worker/native-thread counts, disk I/O, and concurrent query latency.
- Full-day catch-up and long-horizon index size/search, with bounded queues and
  quality-preserving resource reductions on smaller hosts. Thermal/endurance
  behavior and storage growth require measurement beyond a single pipeline run.

Start ML feasibility in parallel with durable ingestion using synthetic or
explicitly redistributable public material with documented provenance. Do not use
private images, OCR, paths, or model outputs as committed fixtures/evidence. Add
benchmark runners only when executable experiments exist; no green benchmark or
hardware-sufficiency claim is made here.

## Delivery Plan and Gates

**Stage 0 — foundation decisions and minimal contract.** Confirm trusted boundary,
key custody/recovery, enrollment and revocation, then specify the thin public
ingestion slice in [contracts](../../contracts/docs/ingestion-design.md). Resolve
owner/device/time/payload semantics with Android; do not design the whole future
API first. Stack acceptance and the first implementation's checks need independent
review. ML feasibility work can proceed separately on safe datasets.

**Stage 1 — durable ingestion and authorized originals.** If the recommendation is
accepted, implement Go core ingestion, PostgreSQL metadata/queue, device auth, and
original reads. Prove pairing -> upload -> durable acknowledgment -> restart ->
authorized retrieval -> safe repeat, with another owner denied. Test outcomes,
not just response codes: unchanged bytes/identity, no premature receipt, durable
work, restart/lost-ACK recovery, conflicting retries, corrupt input, storage-full
and publication/commit faults, revoked devices, and no sensitive logging. This
slice must work without Android runtime, cloud credentials, or inference models.

**Stage 2 — visual retrieval.** Add bounded inference, quality/selection diagnostics,
versioned whole-frame and selective crop embeddings, and local visual retrieval.
Demonstrate “find the yellow screwdriver” against expected episodes. Gate on model
reproducibility, malformed-worker-output rejection, tenant retrieval isolation,
measured recall and end-to-end throughput, and offline/Cloud-AI-off behavior.

**Following slices.** Add OCR detection/recognition plus text indexes and episode
aggregation; temporal neighbors/viewing; lazy provenance and stable observations;
then optional cloud VLM and voice/client dialogue integration. Each slice needs
its own contract only when public behavior is required, plus evidence-backed
uncertainty and regression scenarios. Local speech recognition remains client
work; the proposed offline recognizer's accuracy needs evaluation.

Component tests, including a local declared PostgreSQL service, stay in `server/`.
Contracts own schema/examples/conformance definitions; cross-component retry and
compatibility scenarios belong in [integration/](../../integration/README.md).
Test mismatched supported clients/servers and persisted old recordings, not just
matching checkouts. Each first executable target brings documented component-local
build/lint/style/test commands and applicable CI; the ingestion targets now exist
and their current checks are documented in [quality gates](quality.md).
Independent main-agent verification and review remain merge gates.

Before relying on phone eviction or operational recovery, prove backup restoration
of originals, metadata, owner scope, old contract data, and keys on a clean node.
Before shared service, prove administrative controls, fair resource limits, and
isolation across every retrieval/artifact path. Before deletion/cloud use, test
their lifecycle and consent gates from the data-protection design.

## Open Decisions and Coordination

| Decision | Responsible scope and trigger |
| --- | --- |
| Final core/inference stack, versions, typed checker and private IPC | Server owner and reviewers before implementation/worker boundary |
| Enrollment trust, credential lifecycle, key storage/rotation/recovery | Security, server and Android owners before public pairing and encrypted persistence |
| Models, vector dimensions, export/precision, keyframe/crop policies | Server/benchmark owners after quality and resource measurements |
| Retention, backup policy, deletion/tombstones, phone eviction | Product, server, contracts and Android before cleanup/deletion ships |
| Individual-JPEG byte resume versus whole-file retry | Contracts/server/Android after transfer measurements; batch restart/resume is required |
| Capture/session fields and public/private phone storage | Android/contracts/security coordination against the eventual reviewed mobile revision |
| Index layout, SSD/HDD tiering, Compose/process topology | Server/deploy after capacity and operational measurements |
| Shared service or E2EE/attested mode | New explicit product/security review before changing trust or deployment scope |

The Android public Gallery prototype, six profiles, and expanded session metadata
are now implemented under accepted
[ADR 0004](../../docs/decisions/0004-capture-profiles-public-pictures.md); acceptance
is not device evidence. Android synchronization remains unimplemented, and final
mapping must use the reviewed mobile revision. Do not infer new on-wire
owner/device fields or silently change the mobile storage choice as part of the
server proposal. Gallery consent is not consent for MemoTrace cloud analysis.

# ADR 0007: Bounded Object Retrieval and Candidate History

Status: Accepted — bounded experimental implementation direction

Decision recorded: 2026-09-09, under user direction to implement retrieval,
candidate history and crop experiments using Open Images; authorized/licensed Ego4D
access occurred only in a later external diagnostic. This accepts an
**unreleased baseline**, not a final-best-model choice,
security certification or verified production deployment. All independent-review
findings must be resolved and applicable current-source checks rerun before delivery;
hosted CI, PR/merge and deployment gates remain pending.

## Context

[ADR 0006](0006-ingestion-v0-1.md) accepted durable local-first Go ingestion.
Its no-ML/no-search description records that earlier slice; this decision extends
it without rewriting that history or accepting every proposal in
[ADR 0005](0005-server-foundation.md). Preserved originals now support a concrete
search experiment, while evidence about semantic candidates must remain distinct
from physical-object identity and chronological history.

## Decision

- **Bounded exact baseline:** Go owns archive-scoped dataset/frame assets, durable
  indexing leases, persistence, search and history. PostgreSQL stores vectors;
  search scans the complete requested generation for exact cosine, with at most
  **5000 assets in the archive and 50000 stored regions in the generation**.
  Exceeding either scope fails before query filtering/ranking. There is no
  pgvector/ANN implementation or long-archive capacity claim.
- **Optional offline inference:** the server-owned Python worker uses a closed set
  of pinned SigLIP2 checkpoints. Current source-local fresh v3 evidence selects
  `google/siglip2-base-patch16-224` for continued visual-query work and keeps full
  indexing as the default. This supersedes the historical provisional Base384 text-
  retrieval choice for this scoped visual-query work, but is not a final-best-model
  decision. Continue comparing full-frame letterboxing with full-frame plus
  deterministic overlapping crops;
  crop boxes are coarse match regions, not learned detections. Go controls bounded
  JSONL subprocess lifecycle and jobs; inference owns no SQL transactions, job
  retries or archive deletion. Inference uses pre-acquired, verified artifacts,
  with no runtime download or fake production fallback. Model/preprocessing/runtime
  and spatial-policy fingerprints identify separate index generations.
- **Image/text candidates and honest history:** expose local CLI and authenticated
  HTTPS queries. Score each asset by its maximum region cosine; image queries
  exclude their source asset and identical-byte aliases. Scores are not calibrated
  probabilities. History groups qualifying observations only in an explicitly
  selected real wall/sequence clock, preserving source provenance, cutoff and
  coverage semantics. Unknown times remain unknown. Candidate matches do not
  establish learned stable physical-object identity, tracking or acquisition.
- **Public-data experiment:** use the documented Open Images pilot to compare
  class-level image/text rankings and full/overlap costs. Candidate indexing never
  sees ground-truth labels/boxes; a ground-truth query crop is an explicitly
  identified evaluation proxy. Open Images has no observation chronology: history
  is unavailable, first/last bounds are null and candidates remain unsequenced.
  No Android capture metadata or public-data chronology is fabricated. A later
  private selected-cohort Ego4D diagnostic informs cadence/staging experiments but
  does not establish canonical media, source-video/PTS/frame-zero provenance, stable
  identity, tracking, chronology, an official VQ2D score, or a population estimate.
  Authorized/licensed access and downloaded private media and annotations were used,
  but independently reproducible licensed acquisition provenance was not established
  and official VQ2D evaluation was not run.
- **Contract families and autonomy:** unreleased bundle **0.2.0** contains frozen
  ingestion wire **0.1.0** and retrieval wire **0.2.0**. Preserve ingestion schema/
  OpenAPI bytes, responses and receipt meanings. Canonical definitions remain in
  `contracts/`; the server consumes a generated, read-only five-artifact snapshot
  with family versions, SHA-256 hashes and explicit provenance. The server snapshot
  records canonical source revision `5f5ac49e03b25f805f5a89f791727d0c3bd18642`,
  labeled `unreleased-revision`; that revision contains the exact canonical bytes,
  but bundle 0.2.0 remains unreleased.
  Review source/snapshot/version changes together under the
  [compatibility policy](../../contracts/docs/releases.md). Ordinary component
  builds remain autonomous; root assembly alone compares the selected sibling.
- **Deployment and privacy:** indexing is an explicit offline operator command
  with the service stopped, not an online scheduler. The standalone `server/`
  Docker context still builds **only Go**; optional Python/model provisioning is
  separate, and a combined deployment image is not built. The same-UID worker's
  bounded IPC and credential-free environment are not an OS filesystem/egress
  sandbox. Operator encryption deployment is deferred only for public/synthetic
  experiments. This does not authorize unencrypted private capture: encrypted
  storage/backups, key custody and verified recovery remain operator prerequisites.

## Consequences and Evidence

The [dated main-verification report](../../server/docs/retrieval-main-verification-2026-09-10.md)
records historical pre-hardening local contract, Python and full Go checks, plus the
then-current genuine-model benchmark, worker smoke and Go/PostgreSQL CLI/TLS checks.
This evidence identifies only its recorded source and artifacts/fingerprints, not
the changed source, a new commit on `main`, a PR or a release. The
[2026-09-13 evidence record](../../server/benchmarks/everyday-object-evaluation-2026-09-13.md)
adds current-source fresh v3 checkpoint results and a safe aggregate-only private
Ego4D diagnostic. It selects Base224 for visual-query work and full indexing as the
default without a final-best-model or official VQ2D claim. Current genuine-model Go
CLI/TLS, hosted CI, PR/merge, release, deployment, Android/device and production
evidence remain pending.
The linked [everyday-object evaluation](../../server/benchmarks/everyday-object-evaluation-2026-09-10.md)
records the staged prior-source thread matrix and three-checkpoint comparison, plus
the historical pre-hardening final 100-image Base384 language/data evaluation.

The [historical 48-image Open Images pilot](../../server/benchmarks/openimages-pilot-2026-09-09.md),
[review-v2 rerun](../../server/benchmarks/openimages-pilot-review-v2-2026-09-09.md),
[genuine-worker Go CLI/TLS record](../../server/docs/retrieval-verification-2026-09-09.md)
and [Go review-fix record](../../server/docs/retrieval-review-verification-2026-09-09.md)
are historical builder evidence at their recorded revisions/fingerprints. Primary
text means require both positive and negative judgments and include three classes;
unknown labels are not negatives. The small selected corpus remains sparsely judged,
and class-level condensed rankings are not same-instance accuracy. Neither its
timings nor successful real-worker requests prove full-archive throughput,
chronological-history quality, device sync or private deployment readiness.

[Root CI](../../.github/README.md) coordinates contract validation, read-only
canonical/snapshot parity, Python unit/strict-type/lint/format checks, the full Go
PostgreSQL/race/fault verifier and the standalone Go Docker build. The independently
approved component gates are implemented: **>=85% statement coverage separately
for `internal/protocol` and `internal/retrieval`**, and **>=95% statement coverage
for `memotrace_ml.images`**. Python branch coverage is reported separately without
a branch threshold; package averages or combined line/branch percentages cannot
substitute for these gates.

Root CI installs/tests the locked ML project before the Go verifier and supplies
`MEMOTRACE_TEST_ML_PYTHON="$PWD/ml/.venv/bin/python"` from `server/`. It must exercise
`TestHTTPPythonDecodeFailureAndExactQueryPixels`, covering genuine Pillow decoding
and exact-pixel query interoperability with a test-only encoder and no model/network
requirement. Standalone Go verification may skip this opt-in check without that
interpreter variable and remains independent of an installed ML environment.
Hosted CI remains pending. Subsequent implementation changes require renewed
applicable review and local component/extraction evidence before merge.

Use the component [retrieval guide](../../server/docs/retrieval.md),
[ML commands/model manifest](../../server/ml/README.md) and
[explicit pilot commands](../../server/benchmarks/README.md#repeat-the-public-data-experiment)
for operation and reproduction. Ordinary CI can install locked CPU wheels but
does not acquire model weights or datasets. Keep downloaded images, annotations,
attribution, weights and raw reports outside Git; record artifact hashes and actual
model/policy fingerprints with evidence. Check the candidate's **Apache-2.0** model
license, dataset provenance/attribution and the repository's
[release licensing requirements](../licensing.md#release-and-extraction-checklist).
Original project code/docs remain **AGPL-3.0-only**; third-party licenses are separate.

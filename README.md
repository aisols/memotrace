# MemoTrace

Your private visual memory.

MemoTrace is a local-first visual archive for finding everyday objects and
recovering the context of past events. The product goal is for an Android phone
to record images and a home server to store originals, build search indexes, and
retrieve supporting episodes. Optional cloud vision-language analysis is part of
the future design. Bounded local image/text retrieval and candidate history now
have an executable experimental baseline.

## Status

The first [Android recorder prototype](android/README.md) is buildable: adaptive
JPEG capture, durable local storage, Russian controls, local tests, coverage gates
and executable CI orchestration. Independent review, hosted CI and reference-device
verification remain separate gates; implementation is not hardware evidence.

The [Go ingestion and experimental retrieval server](server/README.md) and
[contract bundle 0.2.0](contracts/README.md) are executable, **unreleased** development
components. The server provides TLS-only local-CLI enrollment, archive-scoped
device credentials, immutable metadata registration, exact JPEG upload/read and
stable historical receipts using PostgreSQL 15 and a private Linux data root.
The bundle preserves ingestion wire **0.1.0** and adds retrieval wire **0.2.0**.
Contract, Go and Python ML verification commands are wired in
[ingestion CI](.github/README.md#ingestion-contracts-and-server); local verification
and hosted results are recorded separately.

The [retrieval experiment](server/docs/retrieval.md) adds persistent indexing jobs,
image/text search and candidate history through local CLI and authenticated HTTPS.
It uses **exact cosine**, bounded to **5000 assets per archive and 50000 stored
regions per generation**. The optional offline [Python SigLIP2 worker](server/ml/README.md)
compares full-frame indexing with full-frame plus overlapping crops. Current
source-local model/data diagnostics select Base224 for continued visual-query work
and keep full indexing as the default; this is not a final-best-model choice. Crop
matches and history are candidates, not learned stable object identity or tracking.

The [current dated evaluation](server/benchmarks/everyday-object-evaluation-2026-09-13.md)
records fresh receipt-bound Open Images v3 model/data results and a private selected-
cohort Ego4D diagnostic at source commit `3f99aa9`, using only safe hashes and
aggregates. The [2026-09-10 verification report](server/docs/retrieval-main-verification-2026-09-10.md)
and its linked [evaluation](server/benchmarks/everyday-object-evaluation-2026-09-10.md)
remain historical pre-hardening evidence. Current genuine-model Go/PostgreSQL CLI/TLS,
hosted CI, PR/merge, release and deployment gates remain pending; the new results do
not identify a commit on `main` or a release.

The [historical 48-image pilot](server/benchmarks/openimages-pilot-2026-09-09.md)
and [review-v2 builder rerun](server/benchmarks/openimages-pilot-review-v2-2026-09-09.md)
retain their recorded fingerprints. Primary text means use three classes with both
positive and negative judgments in those historical records. The historical 100-image
everyday-object evaluation had six primary-eligible classes; unknown labels remain
unknown rather than becoming negatives.
Open Images has unknown observation times: no chronology or first/last sightings
are fabricated. Authorized/licensed Ego4D access and downloaded private media and
annotations were used for the external diagnostic. Canonical-media/PTS/frame-zero
and independently reproducible licensed acquisition provenance were not established,
and official VQ2D evaluation was not run; there is no stable-instance, tracking or
chronology claim.

Indexing is an explicit offline operator command, with the service stopped; there
is no automatic online indexing scheduler. Ingestion receipts and initial pending
jobs retain their original meaning. The Docker image is **Go-only**; optional
Python/model deployment needs separate provisioning. Cloud integration, Android
synchronization, speech and advanced device interactions remain future work.
Pairing uses a manually transported CLI payload, with no QR UI or Android enrollment
flow. There is no published API release or supported client/server combination yet.

The initial reference device is a dedicated Samsung Galaxy A33 running Android
16 / One UI 8, with continued access to its existing applications. The reference
server is Linux with a Ryzen 9 5950X, 64 GB RAM, and no GPU.

## Repository

| Directory | Responsibility |
| --- | --- |
| [android/](android/README.md) | Recorder, local queue, synchronization, voice, and accessible user interface |
| [server/](server/README.md) | Ingestion, archive, processing, search, and optional VLM integration |
| [contracts/](contracts/README.md) | Public API and versioned exchange formats |
| [deploy/](deploy/README.md) | Development assembly and deployment of the whole system |
| [integration/](integration/README.md) | Cross-component tests and safe fixtures |
| [docs/](docs/README.md) | Product, architecture, decisions, and interaction requirements |
| [tools/](tools/README.md) | Repository-wide coordination tools |

The three component roots are intended to remain independently buildable and
extractable into separate repositories. They are ordinary directories today;
there are no submodules yet. The outer repository owns system assembly and
cross-component verification, not component implementation details.

## Start Here

- [Product specification](SPEC.md)
- [Architecture and extraction rules](docs/architecture/README.md)
- [Accepted repository-boundary decision](docs/decisions/0001-component-boundaries.md)
- [Accepted ingestion implementation direction](docs/decisions/0006-ingestion-v0-1.md)
- [Accepted bounded retrieval experiment](docs/decisions/0007-object-retrieval.md)
- [Server setup and verification](server/README.md) and [contract checks](contracts/README.md#quality-command)
- [Retrieval setup](server/docs/retrieval.md), [ML checks/model identity](server/ml/README.md), and [explicit public-data pilot commands](server/benchmarks/README.md#repeat-the-public-data-experiment)
- [Recorder interaction requirements](docs/ux/README.md)
- [Contribution guidelines](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Licensing policy](docs/licensing.md)

The specification remains the original product baseline. Later accepted
decisions and interaction clarifications are recorded separately; unresolved
device behavior is not presented as an implemented or verified feature.

## Privacy

Do not commit personal recordings, document images, database dumps, credentials,
signing keys, or downloaded model weights. Use synthetic or explicitly redistributable
fixtures with provenance. Downloaded public images, annotations, attribution and
raw experiment reports also stay outside Git; runtime archives and backups belong
outside the source tree.

The server trusts the local operator. Encrypted disks, coherent encrypted
backups and protected recovery keys are operator-provisioned, not supplied or
attested by the application. Encryption deployment is explicitly deferred for the
current **public Open Images/synthetic-only experiments**. This does not authorize
unencrypted private capture; private deployment still requires operator-provisioned
protection and verified recovery. Historical receipts do not prove current original
availability, ML completion, backup or permission to evict phone data; `/healthz`
reports process liveness. See [security boundaries](SECURITY.md) and
[server storage/recovery limits](server/docs/storage.md).

## License

Unless explicitly stated otherwise, original project material in this
repository is licensed under the GNU Affero General Public License, version 3
only (`AGPL-3.0-only`). See [LICENSE](LICENSE).

Commercial use is permitted under the license. AGPL is a copyleft license, not a
noncommercial license or a requirement to pay the authors. Third-party software,
models, and datasets retain their own licenses; see the [licensing policy](docs/licensing.md).

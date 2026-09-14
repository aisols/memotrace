# Documentation

- [Product specification](../SPEC.md): the original product baseline.
- [Repository workflow](../AGENTS.md): agent ownership, review, and verification gates.
- [Architecture](architecture/README.md): ownership, dependencies, builds, and extraction.
- [Data protection](architecture/data-protection.md): proposed threat model, trusted processing, privacy lifecycle, and alternative trust boundaries.
- [Repository decision](decisions/0001-component-boundaries.md): accepted component boundaries.
- [Licensing decision](decisions/0002-licensing.md): AGPL-3.0-only and its limits.
- [Capture prototype decision](decisions/0003-capture-prototype.md): adaptive JPEG and shadow-mode occlusion diagnostics.
- [Server foundation decision](decisions/0005-server-foundation.md): historical **Proposed** broader Go-core/Python-inference design; ADRs 0006/0007 adopt concrete slices without accepting the whole proposal.
- [Ingestion 0.1.0 decision](decisions/0006-ingestion-v0-1.md): **Accepted implementation direction**, unreleased local-first TLS/CLI ingestion, storage/trust boundaries and verification limits; not security certification.
- [Object retrieval decision](decisions/0007-object-retrieval.md): **Accepted bounded experiment**, exact cosine over at most 5000 archive assets/50000 generation regions, optional offline SigLIP2 full/overlap worker, image/text candidates and explicit-clock history.
- [Server design](../server/docs/design.md): ingestion/retrieval baseline and proposed broader pipelines; [setup](../server/README.md), [retrieval semantics and CLI/TLS commands](../server/docs/retrieval.md) and [quality](../server/docs/quality.md) own implementation detail. Docker remains Go-only.
- [Python ML worker](../server/ml/README.md): local unit/type/lint checks and approved spatial statement-coverage gate, pinned candidate model/license, full-frame and overlapping-crop policies, explicit offline-worker smoke.
- [Current object-search evidence](../server/benchmarks/object-search-experiment-2026-09-14.md): first usable [offline proposal/descriptor experiment](../server/docs/object-search-experiment.md), public and private aggregate diagnostics, cohort-bound v7 repeat, and passing 100-image genuine-model Go CLI/TLS smoke with independent exact-query matching. Actual source hashes bind uncommitted work over `39b24e3`; production stays Base224 full, with no new history endpoints, database object associations or user confirmation. A narrow PTS scan does not establish canonical content/frame-zero or whole-cohort timing. Server-source extraction passed with provisioned dependencies; official VQ2D, hosted/delivery/deployment, Android/device and production gates remain pending.
- [2026-09-13 model/data evidence](../server/benchmarks/everyday-object-evaluation-2026-09-13.md): historical receipt-bound Open Images v3 checkpoint comparison and selected-cohort private Ego4D diagnostic at `3f99aa9`, preserving its original provenance and limitations.
- [Dated main retrieval verification](../server/docs/retrieval-main-verification-2026-09-10.md): historical pre-hardening local component and genuine Base384 Go/PostgreSQL CLI/TLS evidence, not current-source integration evidence.
- [Public-data experiments](../server/benchmarks/README.md): explicit v3 acquisition/pilot commands, the current dated evidence above, and the [historical Base384 everyday-object evaluation](../server/benchmarks/everyday-object-evaluation-2026-09-10.md) over v2 data. The [original pilot](../server/benchmarks/openimages-pilot-2026-09-09.md), [review-v2 builder rerun](../server/benchmarks/openimages-pilot-review-v2-2026-09-09.md), [Go CLI/HTTPS evidence](../server/docs/retrieval-verification-2026-09-09.md) and [Go review-fix evidence](../server/docs/retrieval-review-verification-2026-09-09.md) retain their historical scope. Open Images has no chronology; the private diagnostic establishes no stable instance/tracking or official VQ2D claim.
- [Contract bundle 0.2.0](../contracts/README.md): frozen ingestion wire **0.1.0** plus retrieval wire **0.2.0**; [ingestion protocol](../contracts/docs/protocol.md), [retrieval protocol](../contracts/docs/retrieval.md), [quality](../contracts/docs/quality.md) and [snapshot/release policy](../contracts/docs/releases.md). No published release or supported client/server matrix yet.
- [Repository automation](../.github/README.md): Android gates and coordinated contract/ML/Go checks with approved component coverage gates, ML-first model-free decoder/pixel interoperability, read-only five-artifact snapshot parity and standalone Go Docker build; model/data downloads are explicit external experiments, and hosted/main-agent evidence remains separate.
- [Security boundary](../SECURITY.md): trusted processing and operator-owned encryption/recovery; encryption deployment is deferred only for public/synthetic experiments, not private capture. Downloaded model/data artifacts stay outside Git.
- [Interaction requirements](ux/README.md): recorder behavior and accessibility.
- [Licensing policy](licensing.md): contributions, third-party material, and releases.

General product and cross-component decisions live here. Implementation details,
build instructions, and component-specific tests belong in the owning component.

Architecture decision records use sequential filenames such as
`0001-component-boundaries.md`. Each records status, context, decision, and
consequences. New decisions may supersede earlier ones without erasing their
reasoning. An accepted requirement is not evidence of implemented behavior.

# Documentation

- [Product specification](../SPEC.md): the original product baseline.
- [Repository workflow](../AGENTS.md): agent ownership, review, and verification gates.
- [Architecture](architecture/README.md): ownership, dependencies, builds, and extraction.
- [Data protection](architecture/data-protection.md): proposed threat model, trusted processing, privacy lifecycle, and alternative trust boundaries.
- [Repository decision](decisions/0001-component-boundaries.md): accepted component boundaries.
- [Licensing decision](decisions/0002-licensing.md): AGPL-3.0-only and its limits.
- [Capture prototype decision](decisions/0003-capture-prototype.md): adaptive JPEG and shadow-mode occlusion diagnostics.
- [Server foundation decision](decisions/0005-server-foundation.md): historical **Proposed** Go-core/Python-inference design; Go is now adopted for the accepted ingestion slice, while Python/ML remains unimplemented.
- [Ingestion 0.1.0 decision](decisions/0006-ingestion-v0-1.md): **Accepted implementation direction**, unreleased local-first TLS/CLI ingestion, storage/trust boundaries and verification limits; not security certification.
- [Server design](../server/docs/design.md): implemented ingestion subset and proposed broader pipelines, benchmarks and delivery gates; [setup](../server/README.md) and [quality](../server/docs/quality.md) own executable commands.
- [Ingestion contract](../contracts/README.md): executable, unreleased 0.1.0 OpenAPI/JSON Schema; [normative protocol](../contracts/docs/protocol.md), [quality](../contracts/docs/quality.md) and [snapshot/release policy](../contracts/docs/releases.md). No published release or supported client/server matrix yet.
- [Repository automation](../.github/README.md): Android gates and coordinated contract/server checks; hosted results and main-agent verification are separate evidence.
- [Interaction requirements](ux/README.md): recorder behavior and accessibility.
- [Licensing policy](licensing.md): contributions, third-party material, and releases.

General product and cross-component decisions live here. Implementation details,
build instructions, and component-specific tests belong in the owning component.

Architecture decision records use sequential filenames such as
`0001-component-boundaries.md`. Each records status, context, decision, and
consequences. New decisions may supersede earlier ones without erasing their
reasoning. An accepted requirement is not evidence of implemented behavior.

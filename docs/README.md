# Documentation

- [Product specification](../SPEC.md): the original product baseline.
- [Repository workflow](../AGENTS.md): agent ownership, review, and verification gates.
- [Architecture](architecture/README.md): ownership, dependencies, builds, and extraction.
- [Data protection](architecture/data-protection.md): proposed threat model, trusted processing, privacy lifecycle, and alternative trust boundaries.
- [Repository decision](decisions/0001-component-boundaries.md): accepted component boundaries.
- [Licensing decision](decisions/0002-licensing.md): AGPL-3.0-only and its limits.
- [Capture prototype decision](decisions/0003-capture-prototype.md): adaptive JPEG and shadow-mode occlusion diagnostics.
- [Server foundation decision](decisions/0005-server-foundation.md): **Proposed**; agreed trusted-processing direction and preferred Go core/Python inference recommendation for review.
- [Server design](../server/docs/design.md): proposed pipelines, technology rationale, durability, benchmarks, and delivery gates.
- [Ingestion contract design](../contracts/docs/ingestion-design.md): proposed initial public semantics; no published API/schema/version yet.
- [Interaction requirements](ux/README.md): recorder behavior and accessibility.
- [Licensing policy](licensing.md): contributions, third-party material, and releases.

General product and cross-component decisions live here. Implementation details,
build instructions, and component-specific tests belong in the owning component.

Architecture decision records use sequential filenames such as
`0001-component-boundaries.md`. Each records status, context, decision, and
consequences. New decisions may supersede earlier ones without erasing their
reasoning. An accepted requirement is not evidence of implemented behavior.

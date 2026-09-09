# ADR 0001: Extractable Components in a Monorepository

Status: Accepted

## Context

The initial team develops on one Linux server, including Android builds and
wireless device testing. A monorepository simplifies coordinated early changes.
Later, parts of the project may need independent repositories and releases.

Repository extraction becomes expensive when components depend on sibling source
paths, parent build settings, shared mutable schemas, or root-only build logic.

## Decision

Use `android/`, `server/`, and `contracts/` as autonomous component roots. Keep
system deployment and cross-component tests in the outer repository. Public
contracts are versioned independently of implementations.

Builds and component tests must work without the enclosing checkout. Consumers
use pinned contract artifacts or controlled local snapshots, not implicit
`../contracts` dependencies. Workers initially remain part of the server, and
ML computation is isolated internally from orchestration and persistence.

Keep these directories as ordinary Git content now. If extraction becomes useful,
preserve their workspace paths and replace them with commit-pinned submodules.

## Consequences

- Coordinated changes remain simple while the project is young.
- Independent component verification guards against accidental coupling.
- Extraction should change repository plumbing, not application behavior.
- Controlled contract copies require explicit updates and provenance checks.
- Full license text and relevant repository policies must accompany extraction.
- Independent repositories, microservices, and granular Android build modules
  are not created merely because future separation is possible.

See the [architecture rules](../architecture/README.md) for the extraction and
verification checklist.

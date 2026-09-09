# MemoTrace Contracts

Autonomous, language-neutral source of truth for the public protocol and persisted
exchange formats. No API, schema, contract version, or release exists yet.

## Layout

- `openapi/`: canonical public HTTP API definitions.
- `schemas/`: manifest and transferable metadata JSON Schemas.
- `examples/`: synthetic valid/invalid examples with expected outcomes.
- `tests/`: schema validation and public-contract consistency checks.

Define device pairing, upload/retry semantics, integrity checks, archive
acknowledgments, queries, evidence responses, and status here. Specify the meaning
of identifiers, timestamps, checksums, errors, and compatibility rules alongside
the machine-readable formats.

Server ORM classes, SQL migrations, internal job payloads, and mobile UI models
do not belong here. Avoid defining speculative endpoint families before their
first implementation needs a contract.

## Consumption and Versions

Use contract-first development for the public API. Check the server's behavior
and exposed API against the canonical contract; do not maintain a second,
independently edited API definition in the server.

Consumers pin a release artifact or a controlled local snapshot with recorded
source version/revision and checksum. Snapshot refresh is an explicit operation;
consumers must not edit generated copies or require `../contracts` at build time.
Do not require a live server to generate clients during an ordinary build.

Add a `VERSION` file and release procedure when the first contract is established.
Protocol/schema versions are independent of client/server application versions.
Test supported combinations once consumers exist, including persisted recordings
that may be uploaded by an older phone application.

## License

Original contracts and examples are licensed under `AGPL-3.0-only`. There is no
separate permissive SDK or generated-code exception at present. Review generated
artifacts and their licensing before distributing them. The full license is in
the enclosing repository's top-level `LICENSE`; include a complete copy when
extracting or distributing this component independently.

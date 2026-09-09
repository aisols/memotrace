# Versions, compatibility, and controlled distribution

Current `VERSION`: **0.1.0, unreleased development contract**. No public
`contracts/v0.1.0` release, compatibility certification, or supported consumer
matrix is asserted. Paths use `/v1` but that path prefix is not evidence that the
pre-1.0 contract is stable. Contract, application, database-migration, and
model/index versions are independent.

## Compatibility policy

`contract_version` is exactly `0.1.0` wherever the current schemas require it.
Client/server pairs must explicitly agree on the pinned contract. Pairing and
manifest requests deliberately have no version field; endpoints and trusted
bootstrap select the protocol. Unsupported version values fail the relevant
schema; do not invent a new error code or silently reinterpret them. Future
negotiation requires its own reviewed contract change.

All current objects are closed. **Unknown fields are rejected**, including
optional-looking additions. An additive request field breaks an older strict
server; an additive response field breaks an older strict client. Therefore an
addition is not automatically compatible and cannot be called a patch-only
change merely because a property is optional.

- Patch: editorial/tooling/fixture corrections that preserve accepted wire
  instances and normative meaning. Review any correction affecting validation
  behavior or a promised receipt guarantee as a protocol change instead.
- Before 1.0, incompatible wire/semantic changes need a new minor version and
  an explicit migration/coexistence plan. After 1.0, incompatible changes require
  a new major version. Additive changes still require compatibility/version
  review; this policy does not pre-authorize them for a minor or patch bump.
- Never silently alter the meaning of timestamps, digests, optional-null fields,
  error retryability, or historical receipts. Retain their original revision's
  interpretation for persisted recordings and receipts.
- Test shipped old/new client-server combinations and legacy recordings before
  claiming support. Record tested component revisions and contract artifact
  checksums. Matching application version numbers do not establish conformance.

## Controlled development snapshot (consumer-owned)

This is the permitted workflow before published artifacts exist. Ordinary
consumer builds/tests must use a **consumer-local pinned copy**, never
`../contracts`, a live server, an unpinned branch, or a network download for code
generation. Server owns its snapshot creation/refresh and provenance manifest.

1. Select the canonical source tree deliberately. Run the complete contract
   quality command at that tree. Record the checked source revision and whether
   the files include unreleased/uncommitted working-tree changes.
2. Copy these wire artifacts **byte-for-byte**, preserving their relative layout:
   `VERSION`, `openapi/ingestion.json`, `schemas/ingestion.schema.json`. Keep the
   whole schema (all `$defs`), not a hand-maintained subset. Add normative
   `docs/protocol.md`, `docs/releases.md`, and `examples/` if consumed by conformance
   tooling or distributed as documentation; hash every copied file.
3. Compute SHA-256 over each source file's raw bytes, then verify the destination
   bytes match. The consumer's manifest records `contract_version`, source
   repository identity, source revision, explicit working-tree status, refresh
   provenance, and a relative-path-to-SHA-256 map. No timestamps or fake revision
   strings may substitute for content integrity.
4. For **this first working-tree snapshot**, record base source revision
   **`f4e53f8`**, explicitly labeled **unreleased working-tree contract 0.1.0**,
   plus the actual file content hashes. This base revision does not contain the
   new definitions and must not be represented as their final source commit.
   On later reviewed refresh, replace it with the actual source commit/release
   provenance and new verified hashes. Do not fabricate a final revision now.
5. Mark copies generated/read-only in consumer documentation. Fix issues here
   and refresh explicitly; never independently edit the snapshot. Consumer
   build/test checks must reject changed bytes against its manifest.
6. Validate the copied schema/OpenAPI and exercise actual consumer wire behavior
   against that copy. Verify the consumer in an isolated component checkout.
   Review changes to protocol files, hashes, provenance, and supported combinations
   together. A stale/mismatched checksum is a failure, not a reason to bypass it.

Example checksum inspection from the selected component root (no file mutation):

```sh
sha256sum VERSION openapi/ingestion.json schemas/ingestion.schema.json
```

Consumers choose the manifest filename/embedding mechanism; this component does
not write consumer snapshots. The schema's reserved `https://memotrace.example/`
`$id` is a stable offline resource identity, not a hosted artifact promise. Map it
to the pinned local schema; preserve OpenAPI's relative refs. Never resolve it
over the network during an ordinary build.

## Future published release

Publishing requires a separately authorized, reviewed change and release action:

1. Resolve independent review findings and pass the latest revision's component
   checks and applicable consumer/cross-component tests. Record limitations and
   real results; schema success is not deployment/device evidence.
2. Apply the compatibility decision, update `VERSION`, schema `$id` and version
   constant, OpenAPI info, fixtures, tooling project version, and release notes
   coherently. Do not mutate an already distributed version's wire meanings.
3. Build an artifact preserving the component layout. Include canonical documents,
   normative docs, fixtures/expectations, executable tools/tests and their lock,
   the **complete unmodified root AGPL license**, and applicable notices. Exclude
   `.venv`, caches, runtime data, credentials, image archives, and model weights.
4. Record the actual full source revision and per-file SHA-256 manifest; publish
   the artifact digest and release notes with supported combinations and explicit
   limitations. Preserve required corresponding source and license notices.
5. Use the repository's reviewed PR workflow and an explicitly authorized tag
   such as `contracts/v0.1.0` only when that release truly exists. Consumers pin
   the artifact/version/checksum and refresh through review.

No automated publisher or generated SDK is introduced. The original contract
and fixtures are `AGPL-3.0-only`, with no permissive generated-code exception.
Review third-party notices if distributing the validation environment itself.

# Repository Architecture

## Ownership

MemoTrace begins as a monorepository with three extractable component roots:
`android/`, `server/`, and `contracts/`. `deploy/`, `integration/`, `docs/`, and
`tools/` form the outer assembly and collaboration layer.

A source component, a running process, and a Git repository are distinct units.
The API and processing workers initially belong to the same server component;
running separate processes does not require separate repositories or releases.

## Dependency Rules

- Android communicates with the server through the public protocol.
- `contracts/` owns public API and exchange-format definitions, not application code.
- Components consume explicit, pinned contract artifacts or controlled snapshots.
- The server owns its database schema, archive implementation, and internal jobs.
- Components must not import sibling source trees or parent build configuration.
- Only the assembly layer may depend on the workspace layout.
- Do not introduce an unbounded `shared/` directory or speculative SDK packages.

Contract snapshots are generated copies with provenance, version, and checksum,
not another editable source of truth. Before publishing contract artifacts,
controlled consumer-local snapshots may be used. Ordinary component builds must
not require a sibling `contracts/` checkout or a live server for code generation.

## Independent Builds

Android owns its Gradle settings, wrapper, dependencies, and tests. The server
owns its build manifests, lockfiles, container build, and tests for its stack.
These files are added with working implementations, not placeholder versions.

The [proposed server foundation](../decisions/0005-server-foundation.md) records
the historical Go core/Python inference recommendation and its open decisions.
[ADR 0006](../decisions/0006-ingestion-v0-1.md) adopts Go for the implemented,
unreleased ingestion slice; Python inference remains proposed and unimplemented.
SPEC remains the original baseline.

The server Docker build context is `server/`, not the entire monorepository.
Development Compose may reference `../server` from `deploy/`; this is an explicit
assembly dependency. Production deployment should consume pinned release images.

Component verification must be runnable from an isolated copy of the component,
without sibling sources or parent configuration. Declared dependencies and test
services are allowed; a developer's home configuration is not a build input.
Component tests should not require the personal archive, real cloud credentials,
or network discovery of the reference phone. Device tests are a separate,
explicit Android verification step.

Root CI workflows orchestrate documented component commands and integration
checks. Do not hide essential build logic in a root-only workflow. When a
component is extracted, only its CI entry point should need adapting.

## Internal Boundaries

On the server, model inference accepts data and explicit model settings and
returns results. It must not own SQL transactions, retry policy, or archive
deletion. Job orchestration and persistence remain server responsibilities.
This permits a future processing library extraction without adding a network
service solely to prepare for a repository split.

The [data-protection proposal](data-protection.md) describes the agreed trusted
processing direction, owner isolation, privacy lifecycle, and alternative trust
boundaries. Its controls are proposals, not evidence of deployed security.

Within Android, separate capture, durable local state, synchronization, device
interaction, speech, and accessible UI behavior. Begin with cohesive packages;
add Gradle modules only when their isolation has a concrete benefit.

## Verification Ownership

Component unit and integration tests stay with that component, including tests
against its own database. `integration/` is for cross-component scenarios such
as transfer retries, archive acknowledgments, and client/server compatibility.
Large or private evaluation datasets live outside the repository; commit only
redistributable fixtures and dataset metadata appropriate for publication.

## Versions and Compatibility

Component release versions and public-format versions are independent. Suggested
monorepository tag names are `android/v0.1.0`, `server/v0.1.0`, and
`contracts/v0.1.0`; no such releases or supported versions exist yet.

Document the supported combinations when releases exist. Compatibility is needed
for shipped clients and persisted recordings, not just matching development
checkouts. Database migrations and ML result versions remain server concerns.

Do not add a second hand-maintained component lock manifest merely to duplicate
Git. A monorepository commit already identifies all source versions. Following
extraction, the superproject's submodule commits identify the source combination;
deployment separately pins the actual distributed artifacts.

## Future Extraction

1. Identify the component prefix and check that no build or runtime dependency
   reaches into its parent or siblings.
2. Extract relevant history in a disposable clone using `git filter-repo` or
   `git subtree split`. Keep the original working repository untouched during
   this operation; rewritten commits will generally have different hashes.
3. Include the complete root `LICENSE`, relevant notices, contributor/security
   policies, and any necessary formatting configuration in the extracted root.
   Check documentation links and preserve authorship and license provenance.
4. Verify a clean standalone build and tests; establish component-local CI and
   a release process before publishing the replacement component.
5. Replace the original directory with a submodule at the same path, pinned to
   a reviewed commit. Do not make releases depend on an unpinned branch tip.
6. Run system integration checks and record the tested combination through the
   superproject commit.

Keep submodules directly under the superproject rather than nesting a contracts
submodule inside every consumer. Use versioned dependencies for consumption.
Ordinary users should install APKs and server images, not manage submodules.

## Non-Goals for the Scaffold

No microservice framework, generic plugin platform, package registry, automated
release pipeline, or submodule conversion is introduced at this stage. Add a
separate web component only when a standalone web application is actually built.
